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

    await route.fulfill({
      status: 503,
      contentType: "application/json",
      body: JSON.stringify({ detail: "E2E fixture intentionally unavailable" }),
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
