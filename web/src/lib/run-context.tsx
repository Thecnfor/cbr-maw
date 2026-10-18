import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from "react";

import { errorMessage, loadHealth, loadScenarios } from "@/lib/api";
import { isISODate, todayISO } from "@/lib/format";
import { navigate, paramsToRecord, useRoute } from "@/lib/router";
import type { ExperimentMode, Health, Scenario } from "@/lib/types";

interface RunContextValue {
  health: Health | null;
  healthError: string | null;
  healthLoading: boolean;
  scenarios: Scenario[];
  scenariosError: string | null;
  scenariosLoading: boolean;
  asOf: string;
  scenarioId: string;
  scenario: Scenario | null;
  mode: ExperimentMode;
  setAsOf: (value: string) => void;
  setScenarioId: (value: string) => void;
  setMode: (value: ExperimentMode) => void;
  reload: () => void;
}

const RunContext = createContext<RunContextValue | null>(null);

function normalizeMode(value: string | null): ExperimentMode {
  return value === "independent" || value === "single" ? value : "collaborative";
}

/**
 * 运行上下文：场景、时点、实验模式是驾驶台与对话共享的「同一事实」。
 * 状态保存在 hash 查询参数中（可分享 / 刷新保留），这里只负责派生与写入。
 */
export function RunProvider({ children }: { children: ReactNode }) {
  const route = useRoute();
  const [reloadToken, setReloadToken] = useState(0);
  const loadedOnce = useRef(false);

  const [health, setHealth] = useState<Health | null>(null);
  const [healthError, setHealthError] = useState<string | null>(null);
  const [healthLoading, setHealthLoading] = useState(true);
  const [scenarios, setScenarios] = useState<Scenario[]>([]);
  const [scenariosError, setScenariosError] = useState<string | null>(null);
  const [scenariosLoading, setScenariosLoading] = useState(true);

  useEffect(() => {
    let active = true;
    const force = loadedOnce.current;
    setHealthLoading(true);
    setScenariosLoading(true);

    void Promise.allSettled([loadHealth(force), loadScenarios(force)]).then(
      ([healthResult, scenariosResult]) => {
        if (!active) return;
        if (healthResult.status === "fulfilled") {
          setHealth(healthResult.value);
          setHealthError(null);
        } else {
          setHealth(null);
          setHealthError(errorMessage(healthResult.reason));
        }
        if (scenariosResult.status === "fulfilled") {
          setScenarios(scenariosResult.value);
          setScenariosError(null);
        } else {
          setScenarios([]);
          setScenariosError(errorMessage(scenariosResult.reason));
        }
        setHealthLoading(false);
        setScenariosLoading(false);
        loadedOnce.current = true;
      },
    );

    return () => {
      active = false;
    };
  }, [reloadToken]);

  const requestedScenarioId = route.params.get("scenario") ?? "";
  const fallbackScenario = scenarios.length ? scenarios[scenarios.length - 1] : null;
  const scenario =
    scenarios.find((item) => item.scenario_id === requestedScenarioId) ??
    (!requestedScenarioId ? fallbackScenario : null);
  const scenarioId = scenario?.scenario_id ?? requestedScenarioId;

  const requestedAsOf = route.params.get("as_of");
  const asOf = isISODate(requestedAsOf)
    ? requestedAsOf
    : scenario?.as_of ?? todayISO();
  const mode = normalizeMode(route.params.get("mode"));

  const patch = useCallback(
    (values: Record<string, string | undefined>) => {
      const record = paramsToRecord(route.params);
      for (const [key, value] of Object.entries(values)) {
        if (value === undefined || value === "") delete record[key];
        else record[key] = value;
      }
      navigate(route.path, record, { replace: true });
    },
    [route],
  );

  const setAsOf = useCallback(
    (value: string) => {
      if (!isISODate(value)) return;
      patch({ as_of: value });
    },
    [patch],
  );

  const setScenarioId = useCallback(
    (value: string) => {
      const next = scenarios.find((item) => item.scenario_id === value);
      patch({
        scenario: value,
        as_of: next?.as_of ?? asOf,
      });
    },
    [asOf, patch, scenarios],
  );

  const setMode = useCallback(
    (value: ExperimentMode) => {
      patch({ mode: value });
    },
    [patch],
  );

  const reload = useCallback(() => {
    setReloadToken((token) => token + 1);
  }, []);

  const value = useMemo<RunContextValue>(
    () => ({
      health,
      healthError,
      healthLoading,
      scenarios,
      scenariosError,
      scenariosLoading,
      asOf,
      scenarioId,
      scenario,
      mode,
      setAsOf,
      setScenarioId,
      setMode,
      reload,
    }),
    [
      health,
      healthError,
      healthLoading,
      scenarios,
      scenariosError,
      scenariosLoading,
      asOf,
      scenarioId,
      scenario,
      mode,
      setAsOf,
      setScenarioId,
      setMode,
      reload,
    ],
  );

  return <RunContext.Provider value={value}>{children}</RunContext.Provider>;
}

export function useRun(): RunContextValue {
  const context = useContext(RunContext);
  if (!context) throw new Error("useRun 必须在 RunProvider 内使用");
  return context;
}
