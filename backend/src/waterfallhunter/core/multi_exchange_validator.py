import asyncio
import logging
import math
import time
from typing import Any, Dict

from waterfallhunter.config import settings
from waterfallhunter.core.candle_analyzer import MultiTimeframeAnalyzer
from waterfallhunter.core.cascade_intelligence import build_cascade_evidence
from waterfallhunter.core.coinglass import CoinGlassDerivativesClient
from waterfallhunter.core.derivatives import DerivativesAnalyzer
from waterfallhunter.core.microstructure import MicrostructureAnalyzer
from waterfallhunter.core.multi_exchange import MultiExchangeGateway
from waterfallhunter.core.position_calculator import PositionCalculator
from waterfallhunter.core.score_v2 import ScoreV2
from waterfallhunter.core.signal_metadata import STRICT_STRATEGY_PROFILE
from waterfallhunter.core.ws_streamer import WebSocketManager


logger = logging.getLogger("WaterfallHunter.Validator")


class MultiExchangeValidator:
    experimental_profile = "experimental_pretrigger_v1"
    armed_threshold = 60
    triggered_threshold = 85
    analysis_prefilter_score = 10
    max_cross_exchange_deviation_pct = 5.0

    benchmark_symbol = "BTC/USDT:USDT"
    benchmark_cache_ttl_seconds = 60.0

    def __init__(self):
        self.gateway = MultiExchangeGateway()
        self.ws_manager = WebSocketManager()
        self.candle_analyzer = MultiTimeframeAnalyzer()
        self.position_calculator = PositionCalculator()
        self.microstructure = MicrostructureAnalyzer()
        self.derivatives = DerivativesAnalyzer()
        self.coinglass = CoinGlassDerivativesClient(
            settings.coinglass_api_key,
            settings.coinglass_base_url,
        )

        self._benchmark_cache: dict[str, tuple[float, dict]] = {}

    @staticmethod
    def _finite_positive(value: Any) -> bool:
        return (
            isinstance(value, (int, float))
            and not isinstance(value, bool)
            and math.isfinite(value)
            and value > 0
        )

    @classmethod
    def _position_reference_price(
        cls,
        ticker: dict[str, Any],
        microstructure: dict[str, Any],
    ) -> tuple[float | None, str | None]:
        """Choose a live price without inventing or carrying stale values."""
        for field in ("mark", "last", "close"):
            value = ticker.get(field)
            if cls._finite_positive(value):
                return float(value), f"ticker.{field}"

        best_bid = microstructure.get("best_bid")
        best_ask = microstructure.get("best_ask")
        if cls._finite_positive(best_bid) and cls._finite_positive(best_ask):
            return (float(best_bid) + float(best_ask)) / 2.0, "orderbook.mid"

        return None, None

    @staticmethod
    def _finite_number(value: Any) -> float | None:
        if (
            isinstance(value, (int, float))
            and not isinstance(value, bool)
            and math.isfinite(value)
        ):
            return float(value)
        return None

    @staticmethod
    def _stage_chain_complete(stages: Dict[str, Any]) -> bool:
        return bool(
            isinstance(stages, dict)
            and stages.get("passed") is True
            and all(
                stages.get(stage) is True
                for stage in (
                    "hype",
                    "damage",
                    "setup",
                    "trigger",
                )
            )
        )

    @staticmethod
    def _observational_status(stages: Dict[str, Any]) -> str:
        """
        Transitional bridge only.

        This is intentionally not the authoritative v3 classifier.
        """
        if not isinstance(stages, dict):
            return "WATCH"

        hype = stages.get("hype") is True
        damage = stages.get("damage") is True
        setup = stages.get("setup") is True
        trigger = stages.get("trigger") is True

        if hype and (damage or setup or trigger):
            return "PRE-TRIGGER"

        if hype:
            return "FUEL-RICH"

        return "WATCH"

    @classmethod
    def _experimental_pretrigger_eligible(
        cls,
        *,
        enabled: bool,
        threshold: float,
        observation_score: Any,
        observation_status: str,
        strategy_stages: Dict[str, Any],
        quality_gates: Dict[str, Any],
        microstructure: Dict[str, Any],
        derivatives: Dict[str, Any],
    ) -> bool:
        required_gates = (
            "all_timeframes_valid",
            "complete_candle_packet",
            "complete_microstructure_packet",
            "complete_fresh_derivatives_packet",
            "taker_sell_dominance",
            "complete_price_location",
            "live_orderbook",
        )
        return bool(
            enabled
            and isinstance(observation_score, (int, float))
            and not isinstance(observation_score, bool)
            and math.isfinite(float(observation_score))
            and float(observation_score) >= float(threshold)
            and observation_status == "PRE-TRIGGER"
            and strategy_stages.get("hype") is True
            and strategy_stages.get("trigger") is True
            and microstructure.get("approved") is True
            and derivatives.get("available") is True
            and all(quality_gates.get(name) is True for name in required_gates)
        )

    @classmethod
    def _relative_return_features(
        cls,
        candidate_details: dict,
        benchmark_details: dict,
    ) -> dict:
        """
        Measure candidate return relative to BTC.

        Negative relative return means the candidate underperformed BTC.

        This method intentionally applies no threshold, state transition,
        or trading decision.
        """
        result: dict[str, Any] = {
            "available": False,
            "benchmark": "BTC",
            "timeframes": {},
        }

        available_pairs = 0

        for timeframe in (
            "4h",
            "1h",
            "15m",
            "5m",
        ):
            candidate = candidate_details.get(timeframe)
            benchmark = benchmark_details.get(timeframe)

            if not isinstance(candidate, dict):
                continue

            if not isinstance(benchmark, dict):
                continue

            timeframe_result: dict[str, Any] = {}

            for bars in (3, 6, 12):
                field = f"return_{bars}bars_pct"

                candidate_return = cls._finite_number(
                    candidate.get(field)
                )

                benchmark_return = cls._finite_number(
                    benchmark.get(field)
                )

                relative_return = None

                if (
                    candidate_return is not None
                    and benchmark_return is not None
                ):
                    relative_return = round(
                        candidate_return - benchmark_return,
                        4,
                    )

                    available_pairs += 1

                timeframe_result[field] = (
                    candidate_return
                )

                timeframe_result[
                    f"benchmark_{field}"
                ] = benchmark_return

                timeframe_result[
                    f"relative_{field}"
                ] = relative_return

            result["timeframes"][
                timeframe
            ] = timeframe_result

        result["available"] = available_pairs > 0
        result["available_pairs"] = available_pairs

        return result

    async def _benchmark_context(
        self,
        exchange: Any,
    ) -> dict:
        """
        Fetch BTC perpetual candle features from the same selected venue.

        Benchmark data is strictly observational.

        Failure of this auxiliary measurement layer must never invalidate
        an otherwise valid candidate analysis.
        """
        exchange_name = str(
            getattr(
                exchange,
                "id",
                "unknown",
            )
        )

        now = time.time()

        cache = getattr(
            self,
            "_benchmark_cache",
            None,
        )

        if not isinstance(cache, dict):
            cache = {}
            self._benchmark_cache = cache

        cached = cache.get(
            exchange_name
        )

        if cached is not None:
            cached_at, cached_packet = cached

            if (
                isinstance(cached_at, (int, float))
                and now - float(cached_at)
                <= self.benchmark_cache_ttl_seconds
            ):
                return cached_packet

        gateway = getattr(
            self,
            "gateway",
            None,
        )

        analyzer = getattr(
            self,
            "candle_analyzer",
            None,
        )

        map_symbol = getattr(
            gateway,
            "_map_symbol",
            None,
        )

        analyzer_timeframes = getattr(
            analyzer,
            "timeframes",
            None,
        )

        analyzer_candle_limit = getattr(
            analyzer,
            "candle_limit",
            None,
        )

        closed_candles = getattr(
            analyzer,
            "_closed_candles",
            None,
        )

        evaluate = getattr(
            analyzer,
            "_evaluate",
            None,
        )

        if (
            not callable(map_symbol)
            or not isinstance(
                analyzer_timeframes,
                (tuple, list),
            )
            or not analyzer_timeframes
            or not isinstance(
                analyzer_candle_limit,
                int,
            )
            or analyzer_candle_limit <= 0
            or not callable(closed_candles)
            or not callable(evaluate)
        ):
            return {
                "available": False,
                "reason": (
                    "benchmark infrastructure unavailable"
                ),
                "source_exchange": exchange_name,
                "mapped_symbol": None,
                "retrieved_at": now,
                "details": {},
            }

        markets = getattr(
            exchange,
            "markets",
            {},
        )

        if not isinstance(markets, dict):
            return {
                "available": False,
                "reason": (
                    "benchmark exchange markets unavailable"
                ),
                "source_exchange": exchange_name,
                "mapped_symbol": None,
                "retrieved_at": now,
                "details": {},
            }

        mapped_symbol = map_symbol(
            self.benchmark_symbol,
            markets,
        )

        if mapped_symbol is None:
            packet = {
                "available": False,
                "reason": (
                    "BTC benchmark unavailable "
                    "on selected exchange"
                ),
                "source_exchange": exchange_name,
                "mapped_symbol": None,
                "retrieved_at": now,
                "details": {},
            }

            cache[exchange_name] = (
                now,
                packet,
            )

            return packet

        fetch_ohlcv = getattr(
            exchange,
            "fetch_ohlcv",
            None,
        )

        if not callable(fetch_ohlcv):
            return {
                "available": False,
                "reason": (
                    "benchmark OHLCV interface unavailable"
                ),
                "source_exchange": exchange_name,
                "mapped_symbol": mapped_symbol,
                "retrieved_at": now,
                "details": {},
            }

        try:
            rows_by_timeframe = await asyncio.gather(
                *(
                    fetch_ohlcv(
                        mapped_symbol,
                        timeframe=timeframe,
                        limit=analyzer_candle_limit,
                    )
                    for timeframe
                    in analyzer_timeframes
                ),
                return_exceptions=True,
            )
        except Exception as exc:
            return {
                "available": False,
                "reason": (
                    "benchmark OHLCV collection failed: "
                    f"{type(exc).__name__}"
                ),
                "source_exchange": exchange_name,
                "mapped_symbol": mapped_symbol,
                "retrieved_at": now,
                "details": {},
            }

        details: dict[str, Any] = {}

        for timeframe, rows in zip(
            analyzer_timeframes,
            rows_by_timeframe,
        ):
            if isinstance(rows, Exception):
                details[timeframe] = {
                    "valid": False,
                    "reason": (
                        "benchmark OHLCV request failed"
                    ),
                }
                continue

            try:
                candles = closed_candles(
                    rows,
                    timeframe,
                )
            except Exception:
                candles = None

            if candles is None:
                details[timeframe] = {
                    "valid": False,
                    "reason": (
                        "benchmark OHLCV invalid or stale"
                    ),
                }
                continue

            try:
                evaluated = evaluate(
                    candles
                )
            except Exception:
                details[timeframe] = {
                    "valid": False,
                    "reason": (
                        "benchmark feature extraction failed"
                    ),
                }
                continue

            details[timeframe] = {
                "valid": True,
                "atr_pct": evaluated.get(
                    "atr_pct"
                ),
                "distance_to_support_atr": (
                    evaluated.get(
                        "distance_to_support_atr"
                    )
                ),
                "support_broken": (
                    evaluated.get(
                        "support_broken"
                    )
                ),
                "lower_high": evaluated.get(
                    "lower_high"
                ),
                "return_3bars_pct": (
                    evaluated.get(
                        "return_3bars_pct"
                    )
                ),
                "return_6bars_pct": (
                    evaluated.get(
                        "return_6bars_pct"
                    )
                ),
                "return_12bars_pct": (
                    evaluated.get(
                        "return_12bars_pct"
                    )
                ),
            }

        available = all(
            isinstance(
                details.get(timeframe),
                dict,
            )
            and details[
                timeframe
            ].get("valid") is True
            for timeframe
            in analyzer_timeframes
        )

        packet = {
            "available": available,
            "reason": (
                None
                if available
                else (
                    "incomplete BTC benchmark "
                    "candle packet"
                )
            ),
            "source_exchange": exchange_name,
            "mapped_symbol": mapped_symbol,
            "retrieved_at": now,
            "details": details,
        }

        cache[exchange_name] = (
            now,
            packet,
        )

        return packet

    def _merge_score_v2(
        self,
        *,
        candles: dict,
        microstructure: dict,
        derivatives: dict,
        cross_exchange_confirmed: bool,
        ticker: dict,
        reference_price: float,
        strategy_stages: Dict[str, Any],
    ) -> dict:
        del reference_price

        last = (
            ticker.get("last")
            if isinstance(ticker, dict)
            else None
        )

        vwap = (
            ticker.get("vwap")
            if isinstance(ticker, dict)
            else None
        )

        price_location = (
            {
                "below_vwap": (
                    float(last)
                    < float(vwap)
                )
            }
            if (
                self._finite_positive(last)
                and self._finite_positive(vwap)
            )
            else {}
        )

        score_result = ScoreV2().evaluate(
            candles,
            microstructure,
            derivatives,
            cross_exchange_confirmed is True,
            price_location,
        )

        quality_gates = {
            **score_result["gates"],
            "channel_stage_chain": (
                self._stage_chain_complete(
                    strategy_stages
                )
            ),
        }

        if not quality_gates[
            "channel_stage_chain"
        ]:
            return {
                "score_version": ScoreV2.version,
                "is_valid": False,
                "score": None,
                "score_components": {},
                "quality_gates": (
                    quality_gates
                ),
                "reason": (
                    "channel stage chain incomplete"
                ),
            }

        return {
            "score_version": (
                score_result[
                    "score_version"
                ]
            ),
            "is_valid": (
                score_result[
                    "is_valid"
                ]
            ),
            "score": (
                score_result[
                    "score"
                ]
            ),
            "score_components": (
                score_result[
                    "components"
                ]
            ),
            "quality_gates": (
                quality_gates
            ),
            "reason": (
                score_result[
                    "reason"
                ]
            ),
        }

    def _watch_score(
        self,
        *,
        candles: dict,
        microstructure: dict,
        derivatives: dict,
        cross_exchange_confirmed: bool | None,
        ticker: dict,
    ) -> dict:
        last = (
            ticker.get("last")
            if isinstance(ticker, dict)
            else None
        )

        vwap = (
            ticker.get("vwap")
            if isinstance(ticker, dict)
            else None
        )

        price_location = (
            {
                "below_vwap": (
                    float(last)
                    < float(vwap)
                )
            }
            if (
                self._finite_positive(last)
                and self._finite_positive(vwap)
            )
            else {}
        )

        return ScoreV2().evaluate_watch(
            candles,
            microstructure,
            derivatives,
            cross_exchange_confirmed,
            price_location,
        )

    def _suggested_status(
        self,
        score: float,
        stages: Dict[str, Any],
        microstructure_approved: bool,
        cross_exchange_confirmed: bool,
    ) -> str:
        if not (
            self._stage_chain_complete(
                stages
            )
            and microstructure_approved
            and cross_exchange_confirmed
        ):
            return "WATCH"

        if score >= self.triggered_threshold:
            return "TRIGGERED"

        if score >= self.armed_threshold:
            return "ARMED"

        return "WATCH"

    async def resolve_live_reference(
        self,
        symbol: str,
    ) -> Dict[str, Any]:
        result = (
            await self.gateway.fetch_ticker(
                symbol
            )
        )

        ticker = (
            result.get("data")
            if result
            else None
        )

        price = (
            ticker.get("last")
            if isinstance(
                ticker,
                dict,
            )
            else None
        )

        if (
            not isinstance(
                price,
                (int, float),
            )
            or price <= 0
        ):
            return {}

        quote_volume = (
            ticker.get("quoteVolume")
            if isinstance(
                ticker,
                dict,
            )
            else None
        )

        return {
            "price": float(price),
            "exchange": (
                result["exchange"]
            ),
            "mapped_symbol": (
                result[
                    "mapped_symbol"
                ]
            ),
            "quote_volume": (
                float(quote_volume)
                if (
                    isinstance(
                        quote_volume,
                        (int, float),
                    )
                    and quote_volume >= 0
                )
                else None
            ),
        }

    @staticmethod
    def _requires_source_fallback(
        microstructure: Dict[str, Any],
    ) -> bool:
        reason = str(
            microstructure.get(
                "reason",
                "",
            )
        )

        return reason.startswith(
            (
                "missing ",
                "empty ",
                "stale ",
                (
                    "orderbook receipt timestamp "
                    "unavailable"
                ),
                (
                    "insufficient fresh trades"
                ),
                (
                    "invalid exchange filters"
                ),
            )
        )

    async def _derivatives_context(
        self,
        symbol: str,
        reference_price: float,
        selected_exchange: str,
        selected_symbol: str,
        selected_instance: Any,
    ) -> dict:
        attempted: list[
            dict[str, Any]
        ] = []

        coinglass_candidates: list[
            tuple[str, str, Any]
        ] = []

        def record_failure(
            exchange_name: str,
            mapped_symbol: str | None,
            market_id: str | None,
            retrieved_at: float | None,
            reason: str,
        ) -> None:
            attempted.append(
                {
                    "exchange": (
                        exchange_name
                    ),
                    "mapped_symbol": (
                        mapped_symbol
                    ),
                    "market_id": (
                        market_id
                    ),
                    "retrieved_at": (
                        retrieved_at
                    ),
                    "reason": reason,
                }
            )

        async def inspect(
            exchange_name: str,
            mapped_symbol: str,
            exchange_instance: Any,
        ) -> dict | None:
            context = (
                await self.gateway
                .fetch_derivatives_context(
                    exchange_instance,
                    mapped_symbol,
                    self.derivatives,
                )
            )

            if context.get(
                "available"
            ):
                context[
                    "fallback_attempts"
                ] = list(
                    attempted
                )

                return context

            record_failure(
                exchange_name,
                context.get(
                    "mapped_symbol",
                    mapped_symbol,
                ),
                context.get(
                    "market_id"
                ),
                context.get(
                    "retrieved_at"
                ),
                str(
                    context.get(
                        "reason",
                        (
                            "derivatives "
                            "unavailable"
                        ),
                    )
                ),
            )
            if context.get("source_capture") is not None:
                attempted[-1]["source_capture"] = context.get("source_capture")

            return None

        if (
            selected_exchange
            == "binance"
        ):
            context = await inspect(
                selected_exchange,
                selected_symbol,
                selected_instance,
            )

            if context is not None:
                return context

            coinglass_candidates.append(
                (
                    selected_exchange,
                    selected_symbol,
                    selected_instance,
                )
            )

        else:
            try:
                binance = (
                    await self.gateway
                    ._get_exchange(
                        "binance"
                    )
                )

            except Exception as exc:
                record_failure(
                    "binance",
                    None,
                    None,
                    None,
                    (
                        "source unavailable: "
                        f"{type(exc).__name__}"
                    ),
                )
            else:
                if not (
                    self.gateway
                    ._markets_loaded
                    .get("binance")
                ):
                    record_failure(
                        "binance",
                        None,
                        None,
                        None,
                        (
                            "markets "
                            "unavailable"
                        ),
                    )

                else:
                    binance_symbol = (
                        self.gateway
                        ._map_symbol(
                            symbol,
                            binance.markets,
                        )
                    )

                    if (
                        binance_symbol
                        is None
                    ):
                        record_failure(
                            "binance",
                            None,
                            None,
                            None,
                            (
                                "no active USDT-linear "
                                "perpetual mapping"
                            ),
                        )

                    else:
                        market = (
                            binance.markets[
                                binance_symbol
                            ]
                        )

                        market_id = (
                            market.get(
                                "id"
                            )
                        )

                        try:
                            ticker = (
                                await asyncio
                                .wait_for(
                                    binance
                                    .fetch_ticker(
                                        binance_symbol
                                    ),
                                    timeout=(
                                        self.gateway
                                        .derivatives_request_timeout_seconds
                                    ),
                                )
                            )

                        except Exception as exc:
                            record_failure(
                                "binance",
                                binance_symbol,
                                market_id,
                                None,
                                (
                                    "price compatibility "
                                    "check unavailable: "
                                    f"{type(exc).__name__}"
                                ),
                            )

                        else:
                            if not (
                                self.gateway
                                ._price_is_compatible(
                                    ticker,
                                    reference_price,
                                    (
                                        self
                                        .max_cross_exchange_deviation_pct
                                    ),
                                )
                            ):
                                record_failure(
                                    "binance",
                                    binance_symbol,
                                    market_id,
                                    None,
                                    (
                                        "price incompatible "
                                        "with reference"
                                    ),
                                )

                            else:
                                context = (
                                    await inspect(
                                        "binance",
                                        binance_symbol,
                                        binance,
                                    )
                                )

                                if (
                                    context
                                    is not None
                                ):
                                    return (
                                        context
                                    )

                                coinglass_candidates.append(
                                    (
                                        "binance",
                                        binance_symbol,
                                        binance,
                                    )
                                )

            context = await inspect(
                selected_exchange,
                selected_symbol,
                selected_instance,
            )

            if context is not None:
                return context

            coinglass_candidates.append(
                (
                    selected_exchange,
                    selected_symbol,
                    selected_instance,
                )
            )

        coinglass_client = getattr(
            self,
            "coinglass",
            None,
        )

        if (
            coinglass_client
            is not None
        ):
            for (
                exchange_name,
                mapped_symbol,
                exchange_instance,
            ) in coinglass_candidates:
                selected_market = (
                    getattr(
                        exchange_instance,
                        "markets",
                        {},
                    )
                    .get(
                        mapped_symbol,
                        {},
                    )
                )

                coinglass = (
                    await coinglass_client
                    .fetch_packet(
                        exchange=(
                            exchange_name
                        ),
                        mapped_symbol=(
                            mapped_symbol
                        ),
                        market_id=(
                            selected_market.get(
                                "id",
                                "",
                            )
                            if isinstance(
                                selected_market,
                                dict,
                            )
                            else ""
                        ),
                        analyzer=(
                            self.derivatives
                        ),
                    )
                )

                if coinglass.get(
                    "available"
                ):
                    coinglass[
                        "fallback_attempts"
                    ] = attempted

                    return coinglass

                record_failure(
                    str(
                        coinglass.get(
                            "source_exchange",
                            "coinglass",
                        )
                    ),
                    coinglass.get(
                        "mapped_symbol"
                    ),
                    coinglass.get(
                        "market_id"
                    ),
                    coinglass.get(
                        "retrieved_at"
                    ),
                    str(
                        coinglass.get(
                            "reason",
                            (
                                "CoinGlass "
                                "derivatives "
                                "unavailable"
                            ),
                        )
                    ),
                )
                if coinglass.get("source_capture") is not None:
                    attempted[-1]["source_capture"] = coinglass.get("source_capture")

        return {
            "available": False,
            "reason": (
                "no complete live derivatives "
                "data source in exchange waterfall"
            ),
            "source_exchange": None,
            "mapped_symbol": None,
            "market_id": None,
            "retrieved_at": None,
            "fallback_attempts": (
                attempted
            ),
        }

    async def cross_check_symbol(
        self,
        symbol: str,
        reference_price: float,
        reference_source: str = "lbank",
    ) -> Dict[str, Any]:
        source_failures = []
        selected = None

        async for wf_result in (
            self.gateway
            .compatible_market_sources(
                symbol,
                reference_price=(
                    reference_price
                ),
                max_deviation_pct=(
                    self
                    .max_cross_exchange_deviation_pct
                ),
            )
        ):
            ticker = (
                wf_result["data"]
            )

            ex_name = (
                wf_result[
                    "exchange"
                ]
            )

            mapped_sym = (
                wf_result[
                    "mapped_symbol"
                ]
            )

            ex_instance = (
                wf_result[
                    "exchange_instance"
                ]
            )

            if not self._finite_positive(
                ticker.get("last")
                if isinstance(
                    ticker,
                    dict,
                )
                else None
            ):
                source_failures.append(
                    {
                        "exchange": (
                            ex_name
                        ),
                        "reason": (
                            "invalid price"
                        ),
                    }
                )
                continue

            orderbook = (
                self.ws_manager
                .get_realtime_orderbook(
                    ex_name,
                    mapped_sym,
                )
            )

            if not orderbook:
                try:
                    orderbook = (
                        await ex_instance
                        .fetch_order_book(
                            mapped_sym,
                            limit=20,
                        )
                    )

                except Exception as exc:
                    source_failures.append(
                        {
                            "exchange": (
                                ex_name
                            ),
                            "reason": (
                                "orderbook "
                                "unavailable: "
                                f"{type(exc).__name__}"
                            ),
                        }
                    )
                    continue

            if (
                not orderbook.get(
                    "bids"
                )
                or not orderbook.get(
                    "asks"
                )
            ):
                source_failures.append(
                    {
                        "exchange": (
                            ex_name
                        ),
                        "reason": (
                            "empty orderbook"
                        ),
                    }
                )
                continue

            (
                confirmation_exchange,
                confirmation_symbol,
            ) = (
                await self.gateway
                .get_confirmation_exchange(
                    symbol,
                    ex_name,
                    reference_price=(
                        reference_price
                    ),
                    max_deviation_pct=(
                        self
                        .max_cross_exchange_deviation_pct
                    ),
                )
            )

            candle_results = (
                await self
                .candle_analyzer
                .analyze_candles(
                    ex_instance,
                    mapped_sym,
                    confirmation_exchange,
                    confirmation_symbol,
                )
            )

            candle_details = (
                candle_results.get(
                    "details",
                    {},
                )
            )

            valid_timeframes = sum(
                bool(
                    candle_details
                    .get(
                        timeframe,
                        {},
                    )
                    .get(
                        "valid"
                    )
                )
                for timeframe in (
                    self.candle_analyzer
                    .timeframes
                )
            )

            if (
                valid_timeframes
                != len(
                    self.candle_analyzer
                    .timeframes
                )
            ):
                source_failures.append(
                    {
                        "exchange": (
                            ex_name
                        ),
                        "reason": (
                            "incomplete completed "
                            "OHLCV"
                        ),
                    }
                )
                continue

            market_info = (
                ex_instance
                .markets
                .get(
                    mapped_sym,
                    {},
                )
            )

            microstructure = (
                await self
                .microstructure
                .analyze(
                    ex_instance,
                    mapped_sym,
                    orderbook,
                    market_info,
                )
            )

            if (
                self
                ._requires_source_fallback(
                    microstructure
                )
            ):
                source_failures.append(
                    {
                        "exchange": (
                            ex_name
                        ),
                        "reason": (
                            microstructure
                            .get(
                                "reason"
                            )
                        ),
                    }
                )
                continue

            metrics = {
                "orderbook": (
                    orderbook
                ),
                "ticker": ticker,
                (
                    "selected_quote_"
                    "volume_usdt"
                ): (
                    float(
                        ticker[
                            "quoteVolume"
                        ]
                    )
                    if self
                    ._finite_positive(
                        ticker.get(
                            "quoteVolume"
                        )
                    )
                    else None
                ),
                "mapped_symbol": (
                    mapped_sym
                ),
                "exchange": (
                    ex_name
                ),
                "data_sources": {
                    "reference": (
                        reference_source
                    ),
                    (
                        "ticker_orderbook_"
                        "candles_trades"
                    ): ex_name,
                    "confirmation": (
                        getattr(
                            confirmation_exchange,
                            "id",
                            None,
                        )
                    ),
                    "primary_exchange": ex_name,
                    "primary_symbol": mapped_sym,
                    "confirmation_exchange": (
                        getattr(
                            confirmation_exchange,
                            "id",
                            None,
                        )
                    ),
                    "confirmation_symbol": confirmation_symbol,
                    "fallback_attempts": (
                        source_failures
                    ),
                },
                "candle_analysis": (
                    candle_results
                ),
                (
                    "valid_candle_"
                    "timeframes"
                ): valid_timeframes,
                "microstructure": (
                    microstructure
                ),
            }

            selected = (
                metrics,
                ticker,
                orderbook,
                ex_instance,
                mapped_sym,
                market_info,
                candle_results,
                microstructure,
            )

            break

        if selected is None:
            return {
                "is_valid": False,
                "score": None,
                "suggested_status": (
                    "REJECTED"
                ),
                "metrics": {
                    "error": (
                        "no complete live USDT "
                        "perpetual data source in "
                        "exchange waterfall"
                    ),
                    (
                        "max_cross_exchange_"
                        "deviation_pct"
                    ): (
                        self
                        .max_cross_exchange_deviation_pct
                    ),
                    "source_failures": (
                        source_failures
                    ),
                },
            }

        (
            metrics,
            ticker,
            orderbook,
            ex_instance,
            mapped_sym,
            market_info,
            candle_results,
            microstructure,
        ) = selected

        derivatives, benchmark = (
            await asyncio.gather(
                self._derivatives_context(
                    symbol,
                    reference_price,
                    metrics[
                        "exchange"
                    ],
                    mapped_sym,
                    ex_instance,
                ),
                self._benchmark_context(
                    ex_instance
                ),
            )
        )

        metrics[
            "derivatives"
        ] = derivatives

        metrics[
            "benchmark_context"
        ] = benchmark

        metrics[
            "data_sources"
        ][
            "derivatives"
        ] = (
            derivatives.get(
                "source_exchange"
            )
            if derivatives.get(
                "available"
            )
            else None
        )

        metrics[
            "data_sources"
        ][
            "benchmark"
        ] = (
            benchmark.get(
                "source_exchange"
            )
            if benchmark.get(
                "available"
            )
            else None
        )

        candle_results = (
            metrics.get(
                "candle_analysis",
                {},
            )
        )

        microstructure = (
            metrics.get(
                "microstructure",
                {},
            )
        )

        candle_details = (
            candle_results.get(
                "details",
                {},
            )
        )

        breakdown_score = candle_results.get(
            "breakdown_score"
        )
        metrics["breakdown_confirmation"] = {
            "primary_bearish_timeframes": (
                breakdown_score
                if isinstance(breakdown_score, int)
                and not isinstance(breakdown_score, bool)
                else None
            ),
            "primary_breakdown_confirmed": (
                breakdown_score >= 2
                if isinstance(breakdown_score, int)
                and not isinstance(breakdown_score, bool)
                else None
            ),
            "confirmation_exchange_15m": (
                candle_results.get("cross_exchange_confirmed")
                if isinstance(
                    candle_results.get("cross_exchange_confirmed"),
                    bool,
                )
                else None
            ),
            "composite_breakdown_confirmed": (
                candle_results.get("is_breakdown_confirmed")
                if isinstance(
                    candle_results.get("is_breakdown_confirmed"),
                    bool,
                )
                else None
            ),
        }

        metrics[
            "candle_features"
        ] = {
            timeframe: {
                "atr_14": (
                    context.get(
                        "atr_14"
                    )
                ),
                "atr_pct": (
                    context.get(
                        "atr_pct"
                    )
                ),
                "dynamic_support": (
                    context.get(
                        "dynamic_support"
                    )
                ),
                (
                    "distance_to_"
                    "support_pct"
                ): (
                    context.get(
                        "distance_to_support_pct"
                    )
                ),
                (
                    "distance_to_"
                    "support_atr"
                ): (
                    context.get(
                        "distance_to_support_atr"
                    )
                ),
                (
                    "distance_from_"
                    "recent_high_pct"
                ): (
                    context.get(
                        "distance_from_recent_high_pct"
                    )
                ),
                (
                    "extension_from_"
                    "support_atr"
                ): (
                    context.get(
                        "extension_from_support_atr"
                    )
                ),
                "return_3bars_pct": (
                    context.get(
                        "return_3bars_pct"
                    )
                ),
                "return_6bars_pct": (
                    context.get(
                        "return_6bars_pct"
                    )
                ),
                "return_12bars_pct": (
                    context.get(
                        "return_12bars_pct"
                    )
                ),
                "lower_high": (
                    context.get(
                        "lower_high"
                    )
                ),
                "support_broken": (
                    context.get(
                        "support_broken"
                    )
                ),
                "regime_bearish": (
                    context.get(
                        "regime_bearish"
                    )
                ),
                "trigger_ready": (
                    context.get(
                        "trigger_ready"
                    )
                ),
                "setup": (
                    context.get(
                        "setup"
                    )
                ),
                "pump_pct": (
                    context.get(
                        "pump_pct"
                    )
                ),
            }
            for (
                timeframe,
                context,
            ) in (
                candle_details.items()
            )
            if (
                isinstance(
                    context,
                    dict,
                )
                and context.get(
                    "valid"
                ) is True
            )
        }

        if benchmark.get(
            "available"
        ):
            metrics[
                "relative_weakness_features"
            ] = (
                self
                ._relative_return_features(
                    candle_details,
                    benchmark.get(
                        "details",
                        {},
                    ),
                )
            )

        else:
            metrics[
                "relative_weakness_features"
            ] = {
                "available": False,
                "benchmark": "BTC",
                "available_pairs": 0,
                "timeframes": {},
                "reason": (
                    benchmark.get(
                        "reason"
                    )
                ),
            }

        metrics[
            "watch_score"
        ] = (
            self._watch_score(
                candles=(
                    candle_details
                ),
                microstructure=(
                    microstructure
                ),
                derivatives=(
                    derivatives
                ),
                cross_exchange_confirmed=(
                    candle_results.get(
                        "is_breakdown_confirmed"
                    )
                ),
                ticker=ticker,
            )
        )

        strategy_stages = (
            self.candle_analyzer
            .channel_stages(
                candle_details
            )
        )

        metrics[
            "strategy_stages"
        ] = strategy_stages

        metrics["cascade_intelligence"] = build_cascade_evidence(
            metrics,
            evaluated_at=int(time.time()),
        )

        if not derivatives.get(
            "available"
        ):
            reason = str(
                derivatives.get(
                    "reason"
                )
                or (
                    "incomplete fresh "
                    "derivatives packet"
                )
            )

            observation_score = (
                metrics[
                    "watch_score"
                ].get(
                    "score"
                )
            )

            observation_state = (
                self
                ._observational_status(
                    strategy_stages
                )
            )

            metrics.update(
                {
                    (
                        "score_version"
                    ): (
                        ScoreV2.version
                    ),
                    "score": None,
                    (
                        "score_components"
                    ): {},
                    (
                        "quality_gates"
                    ): {
                        (
                            "complete_fresh_"
                            "derivatives_packet"
                        ): False
                    },
                    (
                        "analysis_reason"
                    ): reason,
                    "error": reason,
                    (
                        "total_score"
                    ): None,
                    (
                        "trade_eligible"
                    ): False,
                    (
                        "observation_score"
                    ): (
                        observation_score
                    ),
                    (
                        "observation_status"
                    ): (
                        observation_state
                    ),
                    (
                        "observation_"
                        "score_version"
                    ): (
                        metrics[
                            "watch_score"
                        ].get(
                            "score_version"
                        )
                    ),
                    (
                        "observation_"
                        "components"
                    ): (
                        metrics[
                            "watch_score"
                        ].get(
                            "components",
                            {},
                        )
                    ),
                }
            )

            return {
                "is_valid": False,
                "score": None,
                (
                    "suggested_status"
                ): "REJECTED",
                (
                    "observation_score"
                ): (
                    observation_score
                ),
                (
                    "observation_status"
                ): (
                    observation_state
                ),
                "metrics": metrics,
            }

        score_result = (
            self._merge_score_v2(
                candles=(
                    candle_details
                ),
                microstructure=(
                    microstructure
                ),
                derivatives=(
                    derivatives
                ),
                cross_exchange_confirmed=(
                    bool(
                        candle_results.get(
                            "is_breakdown_confirmed"
                        )
                    )
                ),
                ticker=ticker,
                reference_price=(
                    reference_price
                ),
                strategy_stages=(
                    strategy_stages
                ),
            )
        )

        metrics[
            "score_version"
        ] = (
            score_result[
                "score_version"
            ]
        )

        metrics[
            "score"
        ] = (
            score_result[
                "score"
            ]
        )

        metrics[
            "score_components"
        ] = (
            score_result[
                "score_components"
            ]
        )

        metrics[
            "quality_gates"
        ] = {
            "live_orderbook": (
                bool(orderbook)
            ),
            **score_result[
                "quality_gates"
            ],
        }

        metrics[
            "strategy_stages"
        ] = (
            strategy_stages
        )

        metrics[
            "analysis_reason"
        ] = (
            score_result[
                "reason"
            ]
        )

        metrics[
            "total_score"
        ] = (
            score_result[
                "score"
            ]
        )

        experimental_trigger = False

        if not score_result[
            "is_valid"
        ]:
            observation_score = (
                metrics[
                    "watch_score"
                ].get(
                    "score"
                )
            )

            observation_state = (
                self
                ._observational_status(
                    strategy_stages
                )
            )

            metrics[
                "analysis_reason"
            ] = (
                score_result[
                    "reason"
                ]
                or (
                    "strict trade gates "
                    "incomplete"
                )
            )

            metrics[
                "error"
            ] = (
                metrics[
                    "analysis_reason"
                ]
            )

            metrics[
                "score"
            ] = None

            metrics[
                "total_score"
            ] = None

            metrics[
                "score_version"
            ] = (
                ScoreV2.version
            )

            metrics[
                "score_components"
            ] = {}

            metrics[
                "trade_eligible"
            ] = False

            metrics[
                "observation_score"
            ] = (
                observation_score
            )

            metrics[
                "observation_status"
            ] = (
                observation_state
            )

            metrics[
                "observation_score_version"
            ] = (
                metrics[
                    "watch_score"
                ].get(
                    "score_version"
                )
            )

            metrics[
                "observation_components"
            ] = (
                metrics[
                    "watch_score"
                ].get(
                    "components",
                    {},
                )
            )

            experimental_trigger = self._experimental_pretrigger_eligible(
                enabled=bool(settings.experimental_pretrigger_enabled),
                threshold=float(settings.experimental_pretrigger_threshold),
                observation_score=observation_score,
                observation_status=observation_state,
                strategy_stages=strategy_stages,
                quality_gates=metrics["quality_gates"],
                microstructure=microstructure,
                derivatives=derivatives,
            )

            if not experimental_trigger:
                return {
                    "is_valid": False,
                    "score": None,
                    "suggested_status": "REJECTED",
                    "observation_score": observation_score,
                    "observation_status": observation_state,
                    "metrics": metrics,
                }

            base_score = float(observation_score)
            metrics.update(
                {
                    "strategy_profile": self.experimental_profile,
                    "calibration_status": "pending",
                    "experimental_trigger_threshold": float(
                        settings.experimental_pretrigger_threshold
                    ),
                    "score": base_score,
                    "total_score": base_score,
                    "score_version": metrics["watch_score"].get("score_version"),
                    "score_components": metrics["watch_score"].get("components", {}),
                    "analysis_reason": "experimental pre-trigger threshold passed",
                    "trade_eligible": False,
                }
            )
            metrics.pop("error", None)
        else:
            base_score = score_result["score"]
            metrics["trade_eligible"] = True
            metrics["strategy_profile"] = STRICT_STRATEGY_PROFILE

        status = (
            "TRIGGERED"
            if experimental_trigger
            else self._suggested_status(
                base_score,
                strategy_stages,
                bool(microstructure.get("approved")),
                bool(candle_results.get("is_breakdown_confirmed")),
            )
        )

        metrics[
            "total_score"
        ] = base_score

        if (
            status == "TRIGGERED"
            and orderbook
            and ticker
        ):
            # Entry slippage must be applied exactly once. The position
            # calculator adjusts its entry by entry_slippage_pct itself, so
            # pass the raw best bid here; feature replay uses the same input,
            # keeping production and replay decisions identical.
            vwap_entry = (
                microstructure.get(
                    "best_bid"
                )
            )

            history = (
                await ex_instance
                .fetch_ohlcv(
                    mapped_sym,
                    timeframe="5m",
                    limit=1000,
                )
            )

            position_evaluated_at_ms = int(time.time() * 1000)
            metrics.setdefault(
                "source_capture",
                {},
            )["position"] = {
                "attempted": True,
                "timeframe": "5m",
                "requested_limit": 1000,
                "evaluated_at_ms": position_evaluated_at_ms,
                "raw_ohlcv": history,
            }

            mark_price, mark_price_source = (
                self._position_reference_price(
                    ticker,
                    microstructure,
                )
            )

            metrics["position_reference_price"] = {
                "price": mark_price,
                "source": mark_price_source,
            }

            try:
                recent_high = max(
                    float(
                        row[2]
                    )
                    for row in (
                        history[-24:]
                    )
                    if len(row) >= 6
                )

            except (
                TypeError,
                ValueError,
                IndexError,
            ):
                recent_high = None

            pos_setup = (
                self
                .position_calculator
                .calculate_short_position(
                    vwap_entry,
                    recent_high=(
                        recent_high
                    ),
                    market_info=(
                        market_info
                    ),
                    mark_price=(
                        mark_price
                    ),
                    entry_slippage_pct=(
                        microstructure.get(
                            "entry_slippage_pct"
                        )
                    ),
                    exit_slippage_pct=(
                        microstructure.get(
                            "exit_slippage_pct"
                        )
                    ),
                )
            )

            metrics[
                "position_setup"
            ] = pos_setup

            if (
                pos_setup.get(
                    "status",
                    "",
                )
                .startswith(
                    "REJECTED"
                )
            ):
                status = "WATCH"

        return {
            "is_valid": True,
            "score": base_score,
            "suggested_status": (
                status
            ),
            "metrics": metrics,
        }

    async def close_all(self):
        await self.ws_manager.close_all()
        await self.gateway.close_all()
