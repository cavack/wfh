import { expect, test, type Page } from "@playwright/test";

type BrowserErrorLog = string[];

const snapshot = (version: number, generatedAt: number) => ({
  contract_version: "dashboard_snapshot_v1",
  schema_version: "1.0",
  snapshot_version: version,
  generated_at: generatedAt,
  state: "READY",
  total: 0,
  candidates: {},
  final_ranking: {},
  signal_funnel: {},
});

const ancillaryResponses: Record<string, unknown> = {
  "/dashboard/api/execution-outcome-validation": {
    observational_only: true,
    threshold_calibration_allowed: false,
    hard_gating_allowed: false,
    settlement: {
      signal_count: 0,
      settled_outcome_count: 0,
      mature_settlement_coverage_rate: null,
    },
    evidence: {
      status: "INSUFFICIENT_EVIDENCE",
      ready: false,
      decisive_outcome_count: 0,
      observation_span_days: 0,
      requirements: {
        minimum_decisive_outcomes: 100,
        minimum_outcomes_per_status: 20,
        minimum_observation_span_days: 42,
      },
    },
    by_execution_status: {},
  },
  "/dashboard/api/feature-replay": {
    operational: true,
    observational_only: true,
    hard_gating_allowed: false,
    replayed_count: 0,
    equivalent_count: 0,
    mismatch_count: 0,
    not_replayable_count: 0,
    equivalence_rate: null,
    strategy_equivalent: false,
    requirements: {
      minimum_replays: 100,
      triggered_path_replay_required: true,
    },
  },
  "/dashboard/api/historical-outcomes": {
    available: false,
    operational: true,
    observational_only: true,
    hard_gating_allowed: false,
    dataset: null,
    summary: {
      event_count: 0,
      settled_count: 0,
      win_rate: null,
      net_expectancy_r: null,
    },
  },
  "/dashboard/api/production-evidence": {
    operational: true,
    observational_only: true,
    hard_gating_allowed: false,
    snapshot_count_24h: 0,
    symbol_count_24h: 0,
    latest_age_seconds: null,
    coverage: {
      decision_packet_complete_rate: null,
      orderbook_rate: null,
      confirmation_source_rate: null,
    },
    replay: {
      decision_packet_replay: false,
      source_replay_ready: false,
      source_replay_ready_rate: null,
      raw_ohlcv_capture_rate: null,
      raw_trades_capture_rate: null,
    },
  },
  "/dashboard/api/lifecycle-v2-shadow": {
    shadow_only: true,
    promotion_allowed: false,
    event_count: 0,
    divergence_count: 0,
    returned_event_count: 0,
    analysis: {
      state_counts: {},
      episode_count_in_returned_window: 0,
      triggered_episode_count_in_returned_window: 0,
      lead_time_seconds: { available: false, median: null },
      promotion_decision: "DO_NOT_PROMOTE",
    },
    events: [],
  },
  "/dashboard/api/lifecycle-v2-contract": {
    shadow_only: true,
    promotion_allowed: false,
  },
};

async function mockDashboardApis(page: Page): Promise<{ candidateCalls: () => number }> {
  let calls = 0;

  await page.route("**/dashboard/api/**", async (route) => {
    const path = new URL(route.request().url()).pathname;
    if (path === "/dashboard/api/candidates") {
      calls += 1;
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify(snapshot(1, 1_000)),
      });
      return;
    }

    const response = ancillaryResponses[path];
    if (response !== undefined) {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify(response),
      });
      return;
    }

    await route.fulfill({
      status: 501,
      contentType: "application/json",
      body: JSON.stringify({ detail: `Unhandled E2E dashboard API fixture: ${path}` }),
    });
  });

  return { candidateCalls: () => calls };
}

function captureBrowserErrors(page: Page): BrowserErrorLog {
  const errors: BrowserErrorLog = [];
  page.on("console", (message) => {
    if (message.type() === "error") errors.push(message.text());
  });
  page.on("pageerror", (error) => errors.push(error.message));
  return errors;
}

async function installFailingEventSource(page: Page): Promise<void> {
  await page.addInitScript(() => {
    class FailingEventSource {
      static readonly CONNECTING = 0;
      static readonly OPEN = 1;
      static readonly CLOSED = 2;

      readonly CONNECTING = 0;
      readonly OPEN = 1;
      readonly CLOSED = 2;
      readonly url: string;
      readonly withCredentials = false;
      readyState = FailingEventSource.CONNECTING;
      onopen: ((event: Event) => void) | null = null;
      onmessage: ((event: MessageEvent<string>) => void) | null = null;
      onerror: ((event: Event) => void) | null = null;

      constructor(url: string | URL) {
        this.url = String(url);
        window.setTimeout(() => {
          this.readyState = FailingEventSource.CLOSED;
          this.onerror?.(new Event("error"));
        }, 0);
      }

      addEventListener(): void {}
      removeEventListener(): void {}
      dispatchEvent(): boolean { return true; }
      close(): void { this.readyState = FailingEventSource.CLOSED; }
    }

    Object.defineProperty(window, "EventSource", {
      configurable: true,
      value: FailingEventSource,
    });
  });
}

async function installSnapshotEventSource(page: Page): Promise<void> {
  const payload = {
    contract_version: "dashboard_stream_event_v1",
    event_id: "1",
    event_type: "snapshot",
    snapshot_version: 2,
    schema_version: "1.0",
    generated_at: 2_000,
    last_event_id: null,
    payload_hash: "a".repeat(64),
    payload: snapshot(2, 2_000),
    replayed: false,
    full_snapshot: true,
  };

  await page.addInitScript((packet) => {
    class SnapshotEventSource {
      static readonly CONNECTING = 0;
      static readonly OPEN = 1;
      static readonly CLOSED = 2;

      readonly CONNECTING = 0;
      readonly OPEN = 1;
      readonly CLOSED = 2;
      readonly url: string;
      readonly withCredentials = false;
      readyState = SnapshotEventSource.CONNECTING;
      onopen: ((event: Event) => void) | null = null;
      onmessage: ((event: MessageEvent<string>) => void) | null = null;
      onerror: ((event: Event) => void) | null = null;
      private listeners = new Map<string, Set<EventListenerOrEventListenerObject>>();

      constructor(url: string | URL) {
        this.url = String(url);
        window.setTimeout(() => {
          this.readyState = SnapshotEventSource.OPEN;
          this.onopen?.(new Event("open"));
        }, 0);
        window.setTimeout(() => {
          const event = new MessageEvent<string>("snapshot", {
            data: JSON.stringify(packet),
          });
          for (const listener of this.listeners.get("snapshot") ?? []) {
            if (typeof listener === "function") {
              listener.call(this, event);
            } else {
              listener.handleEvent(event);
            }
          }
        }, 50);
      }

      addEventListener(type: string, listener: EventListenerOrEventListenerObject | null): void {
        if (listener === null) return;
        const listeners = this.listeners.get(type) ?? new Set<EventListenerOrEventListenerObject>();
        listeners.add(listener);
        this.listeners.set(type, listeners);
      }

      removeEventListener(type: string, listener: EventListenerOrEventListenerObject | null): void {
        if (listener === null) return;
        this.listeners.get(type)?.delete(listener);
      }

      dispatchEvent(): boolean { return true; }
      close(): void { this.readyState = SnapshotEventSource.CLOSED; }
    }

    Object.defineProperty(window, "EventSource", {
      configurable: true,
      value: SnapshotEventSource,
    });
  }, payload);
}

test("dashboard falls back to polling without weakening PAPER_ONLY safety", async ({ page }) => {
  const errors = captureBrowserErrors(page);
  const api = await mockDashboardApis(page);
  await installFailingEventSource(page);

  await page.goto("/dashboard");

  await expect(page.getByRole("heading", { name: "WaterfallHunter" })).toBeVisible();
  await expect(page.getByText("LIVE TRADING OFF", { exact: true })).toBeVisible();
  await expect(page.getByRole("status").filter({ hasText: "Polling fallback" })).toBeVisible();
  await expect(page.getByText("No active candidates in the latest valid snapshot")).toBeVisible();
  expect(api.candidateCalls()).toBeGreaterThanOrEqual(1);

  await page.getByRole("link", { name: "Backtest Lab" }).click();
  await expect(page).toHaveURL(/#backtest-lab$/);
  expect(errors).toEqual([]);
});

test("named SSE snapshot establishes live-stream state", async ({ page }) => {
  const errors = captureBrowserErrors(page);
  await mockDashboardApis(page);
  await installSnapshotEventSource(page);

  await page.goto("/dashboard");

  await expect(page.getByRole("heading", { name: "WaterfallHunter" })).toBeVisible();
  await expect(page.getByText("LIVE TRADING OFF", { exact: true })).toBeVisible();
  await expect(page.getByRole("status").filter({ hasText: "Live stream" })).toBeVisible();
  await expect(page.getByText("No active candidates in the latest valid snapshot")).toBeVisible();
  expect(errors).toEqual([]);
});
