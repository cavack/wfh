import asyncio

from fastapi import (
    APIRouter,
    HTTPException,
    Query,
    Request,
)

from waterfallhunter.core.lbank_execution_stats import (
    LBankExecutionStats,
)
from waterfallhunter.core.lbank_execution_suitability_report import (
    LBankExecutionSuitabilityReport,
)


_ALLOWED_QUERY_PARAMETERS = frozenset(
    {
        "examples_per_status",
    }
)


def build_execution_suitability_router(
    db_path: str,
) -> APIRouter:
    """
    Build the read-only execution-suitability API router.

    The router is intentionally observational only.

    It must never:
    - mutate scan_eligible
    - mutate catalogue state
    - mutate hunter states
    - mutate scores
    - send alerts
    - place orders
    - accept threshold overrides from API callers
    """
    router = APIRouter()

    stats = LBankExecutionStats(
        db_path=db_path
    )

    report_builder = (
        LBankExecutionSuitabilityReport(
            stats
        )
    )

    @router.get(
        "/api/execution-suitability"
    )
    async def execution_suitability_report(
        request: Request,
        examples_per_status: int = Query(
            default=20,
            ge=0,
            le=100,
        ),
    ):
        unknown_parameters = sorted(
            set(
                request.query_params.keys()
            )
            - _ALLOWED_QUERY_PARAMETERS
        )

        if unknown_parameters:
            raise HTTPException(
                status_code=422,
                detail={
                    "error": (
                        "unsupported query parameter"
                    ),
                    "unsupported_parameters": (
                        unknown_parameters
                    ),
                    "allowed_parameters": sorted(
                        _ALLOWED_QUERY_PARAMETERS
                    ),
                },
            )

        return await asyncio.to_thread(
            report_builder.build_report,
            examples_per_status=(
                examples_per_status
            ),
        )

    return router
