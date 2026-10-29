import { m, useReducedMotion } from "motion/react";
import {
  ArrowRight,
  Check,
  ChevronDown,
  Loader2,
  MapPin,
  Minus,
  Plus,
} from "lucide-react";
import React from "react";
import { useApp } from "../../../../app/state/AppContext";
import { useSendMessage } from "../../../../app/session/useSendMessage";
import { saveIntakeDraft } from "../../../chat/api/sessions";
import { getTripPlannerConfiguration } from "../../api/planner";
import { Button } from "../../../../components/ui/Button";
import { cn } from "../../../../lib/utils";
import { emphasisEnter } from "../../../../lib/motion";
import { DateRangePicker } from "./DateRangePicker";
import { tripIdentityError } from "../../model/tripIdentityValidation";
import { PlaceField } from "./PlaceField";
import { DestinationTokenField, MAX_DESTINATIONS } from "./DestinationTokenField";
import type {
  ControlledTripIdentity,
  GuidedIntakeState,
  IntakeAnswer,
  IntakeDraft,
  PlaceIdentity,
  TripPlannerConfiguration,
} from "../../types/planner";

function initialDraft(intake: GuidedIntakeState): IntakeDraft {
  return {
    origin_query: "",
    destination_queries: [],
    start_date: null,
    end_date: null,
    duration_days: null,
    party: null,
    style: null,
    budget_text: "",
    destination_decided: false,
    destination_suggestions: [],
    confirmed_origin: null,
    confirmed_destinations: [],
    ...intake.draft,
  };
}

export const GuidedIntakeQuestions: React.FC<{ intake: GuidedIntakeState; inline?: boolean }> = ({
  intake,
  inline = false,
}) => {
  const { state, dispatch, currentStateRef } = useApp();
  const { sendMessage } = useSendMessage();
  const reducedMotion = useReducedMotion();
  const mountedRef = React.useRef(true);
  React.useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
    };
  }, []);
  const [draft, setDraft] = React.useState(() => initialDraft(intake));
  const [answers, setAnswers] = React.useState<IntakeAnswer[]>(
    intake.answers ?? [],
  );
  const [additional, setAdditional] = React.useState(
    intake.additional_requirements ?? "",
  );
  const [origin, setOrigin] = React.useState<PlaceIdentity | null>(
    draft.confirmed_origin ?? intake.controlled_identity?.origin ?? null,
  );
  const [destinationField, setDestinationField] = React.useState<{
    values: Array<PlaceIdentity | null>;
    queries: string[];
  }>(() => {
    const confirmed = (
      draft.confirmed_destinations.length
        ? draft.confirmed_destinations
        : intake.seed_destinations?.length
          ? intake.seed_destinations
          : intake.controlled_identity?.destinations
    )?.slice(0, MAX_DESTINATIONS);
    if (confirmed?.length) {
      const trailingQueries = draft.destination_queries
        .slice(confirmed.length)
        .filter((query) => query.trim());
      return {
        values: [...confirmed, ...trailingQueries.map(() => null)],
        queries: [...confirmed.map((place) => place.name), ...trailingQueries],
      };
    }
    if (draft.destination_queries.length) {
      return {
        values: draft.destination_queries.slice(0, MAX_DESTINATIONS).map(() => null),
        queries: draft.destination_queries.slice(0, MAX_DESTINATIONS),
      };
    }
    return { values: [null], queries: [''] };
  });
  const { values: destinations, queries: destinationQueries } = destinationField;
  const updateDestinationField = React.useCallback((values: Array<PlaceIdentity | null>, queries: string[]) => {
    setDestinationField({ values, queries });
  }, []);
  const destination = destinations[0];
  const [config, setConfig] = React.useState<TripPlannerConfiguration | null>(
    null,
  );
  const [error, setError] = React.useState("");
  const [saveState, setSaveState] = React.useState<
    "saved" | "saving" | "error"
  >("saved");
  const [submitting, setSubmitting] = React.useState(false);
  const [detailsOpen, setDetailsOpen] = React.useState(false);
  const [collapsing, setCollapsing] = React.useState(false);
  const initial = React.useRef(true);
  const saveQueue = React.useRef<Promise<unknown>>(Promise.resolve());
  const sessionId = state.currentSessionId;
  const questions = intake.questions ?? [];
  const currentIndex = questions.findIndex(
    (question) =>
      !answers.some(
        (answer) =>
          answer.question_id === question.id &&
          (answer.selected_option_ids.length || answer.supplement.trim()),
      ),
  );
  const question = currentIndex < 0 ? null : questions[currentIndex];
  const [freeText, setFreeText] = React.useState("");
  const [editingQuestion, setEditingQuestion] = React.useState<string | null>(
    null,
  );
  const activeQuestion =
    questions.find((item) => item.id === editingQuestion) ?? question;
  const activeAnswer = answers.find(
    (answer) => answer.question_id === activeQuestion?.id,
  );
  const questionRef = React.useRef<HTMLDivElement>(null);
  const errorRef = React.useRef<HTMLParagraphElement>(null);
  React.useEffect(() => {
    if (inline && activeQuestion?.id) {
      questionRef.current?.focus({ preventScroll: true });
    }
  }, [activeQuestion?.id, inline]);
  React.useEffect(() => {
    if (inline && error) errorRef.current?.focus({ preventScroll: true });
  }, [error, inline]);
  const party = draft.party;
  const style =
    draft.style ??
    (config
      ? {
          primary:
            config.primary_styles.find((item) => item.is_default)?.label ??
            config.primary_styles[0].label,
          secondary_interests: [],
          source: "suggested" as const,
        }
      : null);
  const snapshot = React.useMemo(
    () => ({
      ...intake,
      draft: {
        ...draft,
        confirmed_origin: origin,
        origin_query: origin?.name ?? draft.origin_query,
        destination_queries: [
          ...destinations
            .map((place, index) => place?.name ?? destinationQueries[index] ?? "")
            .filter(Boolean),
          ...destinationQueries
            .slice(destinations.length)
            .map((query) => query.trim())
            .filter(Boolean),
        ],
        confirmed_destinations: destinations.filter(
          (place): place is PlaceIdentity => place !== null,
        ),
        style,
      },
      answers,
      additional_requirements: additional,
    }),
    [
      intake,
      draft,
      origin,
      destinations,
      destinationQueries,
      style?.primary,
      style?.source,
      answers,
      additional,
    ],
  );

  React.useEffect(() => {
    let active = true;
    getTripPlannerConfiguration()
      .then((value) => {
        if (active) setConfig(value);
      })
      .catch(() => {
        if (active) setError("暂时无法读取旅行风格，请稍后刷新重试。");
      });
    return () => {
      active = false;
    };
  }, []);

  React.useEffect(() => {
    if (initial.current) {
      initial.current = false;
      return;
    }
    if (!sessionId || submitting || state.isStreaming) return;
    const saveEpoch = state.conversationEpoch;
    const timer = window.setTimeout(() => {
      if (!mountedRef.current || currentStateRef.current.currentSessionId !== sessionId || currentStateRef.current.conversationEpoch !== saveEpoch) return;
      setSaveState("saving");
      dispatch({ type: "SET_GUIDED_INTAKE", payload: snapshot });
      const saveSessionId = sessionId;
      saveQueue.current = saveQueue.current
        .catch(() => undefined)
        .then(async () => {
          try {
            await saveIntakeDraft(saveSessionId, snapshot);
            if (mountedRef.current && currentStateRef.current.currentSessionId === saveSessionId && currentStateRef.current.conversationEpoch === saveEpoch) setSaveState("saved");
          } catch {
            if (mountedRef.current && currentStateRef.current.currentSessionId === saveSessionId && currentStateRef.current.conversationEpoch === saveEpoch) setSaveState("error");
          }
        });
    }, 500);
    return () => window.clearTimeout(timer);
  }, [draft, answers, additional, origin, destinations, destinationQueries, sessionId, state.conversationEpoch, submitting]);

  const answerQuestion = (optionId?: string) => {
    if (!activeQuestion) return;
    const current = activeAnswer?.selected_option_ids ?? [];
    const ids = optionId
      ? activeQuestion.kind === "single"
        ? [optionId]
        : current.includes(optionId)
          ? current.filter((id) => id !== optionId)
          : [...current, optionId]
      : current;
    setAnswers((items) => [
      ...items.filter((item) => item.question_id !== activeQuestion.id),
      {
        question_id: activeQuestion.id,
        selected_option_ids: ids,
        supplement: freeText.trim() || activeAnswer?.supplement || "",
      },
    ]);
    if (activeQuestion.kind === "single" || !optionId) {
      setEditingQuestion(null);
      setFreeText("");
    } else {
      setEditingQuestion(activeQuestion.id);
    }
  };

  const start = async () => {
    if (submitting || state.isStreaming) return;
    setError("");
    const validation = tripIdentityError({
      origin,
      destinations,
      start_date: draft.start_date ?? "",
      end_date: draft.end_date ?? "",
      party,
      style,
    });
    if (validation) {
      setError(validation);
      return;
    }
    const confirmedDestinations = destinations.filter(
      (place): place is PlaceIdentity => place !== null,
    );
    if (
      !origin ||
      !destination ||
      !draft.start_date ||
      !draft.end_date ||
      !party ||
      !style
    )
      return;
    if (currentIndex >= 0) {
      setError("请先回答上方尚未完成的问题。");
      return;
    }
    const identity: ControlledTripIdentity = {
      origin,
      destinations: confirmedDestinations,
      start_date: draft.start_date,
      end_date: draft.end_date,
      party,
      style,
    };
    const startSessionId = currentStateRef.current.currentSessionId;
    const startEpoch = currentStateRef.current.conversationEpoch;
    const ownsRequest = () => mountedRef.current
      && currentStateRef.current.currentSessionId === startSessionId
      && currentStateRef.current.conversationEpoch === startEpoch;
    setSubmitting(true);
    try {
      await saveQueue.current.catch(() => undefined);
      if (!ownsRequest()) return;
      if (startSessionId) await saveIntakeDraft(startSessionId, snapshot);
      if (!ownsRequest()) return;
      dispatch({ type: "SET_GUIDED_INTAKE", payload: snapshot });
      if (inline && !reducedMotion) {
        if (!ownsRequest()) return;
        setCollapsing(true);
        await new Promise((resolve) => window.setTimeout(resolve, 450));
        if (!ownsRequest()) return;
      }
      if (!ownsRequest()) return;
      const sent = await sendMessage(intake.raw_input, undefined, {
        route: "trip_planning",
        controlledTripIdentity: identity,
        guidedIntake: snapshot,
        displayText: `确认${destination.name}旅行：${draft.start_date} 至 ${draft.end_date}，从${origin.name}出发`,
        assistantPendingLabel: "正在根据已确认的信息准备旅行计划",
      });
      if (!ownsRequest()) return;
      if (!sent) {
        setCollapsing(false);
        setError("暂时无法开始规划，旅行信息已保留，请重试。");
      }
    } catch {
      if (!ownsRequest()) return;
      setCollapsing(false);
      setError("暂时无法保存旅行信息，请重试。");
    } finally {
      if (ownsRequest()) setSubmitting(false);
    }
  };

  const completeCount = [
    origin,
    destinations.every(Boolean),
    draft.start_date && draft.end_date,
    party,
  ].filter(Boolean).length;
  const confirmedNames = destinations
    .filter((place): place is PlaceIdentity => place !== null)
    .map((place) => place.name)
    .join("、");
  if (inline && collapsing) {
    return (
      <m.section
        className="travel-intake travel-intake-inline travel-intake-collapsed"
        data-testid="guided-intake-collapsed"
        aria-label="正在准备正式规划"
        initial={{ opacity: 0.82 }}
        animate={{ opacity: 1 }}
        transition={reducedMotion ? { duration: 0 } : { duration: 0.22 }}
      >
        <div className="travel-intake-collapsed-card" role="status" aria-live="polite">
          <Loader2 size={20} className="animate-spin" aria-hidden />
          <div>
            <p className="travel-intake-eyebrow">确认旅行信息</p>
            <strong>正在准备正式规划…</strong>
            <span>
              {origin?.name ?? "出发地"} → {confirmedNames || "目的地"}
              {draft.start_date && draft.end_date ? ` · ${draft.start_date} — ${draft.end_date}` : ""}
              {party ? ` · ${party.adults} 位成人${party.children ? ` · ${party.children} 位儿童` : ""}` : ""}
            </span>
          </div>
        </div>
      </m.section>
    );
  }
  return (
    <m.section
      className={cn("travel-intake", inline && "travel-intake-inline")}
      data-testid="guided-intake"
      aria-labelledby="travel-intake-title"
      variants={emphasisEnter}
      initial="hidden"
      animate="visible"
      transition={reducedMotion ? { duration: 0 } : undefined}
    >
      {inline ? (
        <header className="travel-intake-inline-header">
          <div>
            <p className="travel-intake-eyebrow">开始规划前</p>
            <h2 id="travel-intake-title">确认旅行信息</h2>
          </div>
          <span className="travel-intake-count">
            {completeCount} / 4 项已确认
          </span>
        </header>
      ) : (
        <header className="travel-intake-header">
          <div>
            <p className="travel-intake-eyebrow">把想法变成一趟旅行</p>
            <h1 id="travel-intake-title">确认旅行信息</h1>
            <p>补齐影响路线和费用的信息，再为你安排每天的行程。</p>
          </div>
          <span className="travel-intake-count">
            {completeCount} / 4 项已确认
          </span>
        </header>
      )}
      <div className={cn("travel-intake-body", inline && "is-inline")}>
        <div className="travel-intake-main">
          {intake.understanding_status === "unavailable" && (
            <p role="status" className="travel-intake-notice">
              暂时没能自动整理你的想法，原文已保留。可以直接确认下方信息继续。
            </p>
          )}
          {draft.destination_suggestions.length > 0 && !destination && (
            <section className="travel-intake-section">
              <h2>可以先考虑这几个地方</h2>
              <div className="travel-destination-options">
                {draft.destination_suggestions.map((item) => (
                  <button
                    type="button"
                    key={item.name}
                    onClick={() => {
                      setDestinationField((current) => {
                        const values = current.values.length ? current.values : [null];
                        const queries = [...current.queries];
                        queries[0] = item.name;
                        return { values, queries };
                      });
                      setDraft((value) => ({
                        ...value,
                        destination_queries: [item.name],
                      }));
                    }}
                    className={cn(
                      draft.destination_queries[0] === item.name &&
                        "is-selected",
                    )}
                  >
                    <MapPin size={16} />
                    <span>
                      <strong>{item.name}</strong>
                      <small>{item.reason}</small>
                    </span>
                    <ArrowRight size={16} />
                  </button>
                ))}
              </div>
            </section>
          )}
          <section className="travel-intake-section">
            <div className="travel-intake-section-title">
              <span>01</span>
              <h2>从哪里，到哪里</h2>
            </div>
            <div className="travel-intake-route">
              <PlaceField
                role="origin"
                label="出发地"
                value={origin}
                onChange={setOrigin}
                initialQuery={draft.origin_query}
                onQueryChange={(origin_query) => setDraft(value => ({ ...value, origin_query }))}
              />
              <ArrowRight size={17} aria-hidden />
              <div className="travel-intake-destination">
                <span className="planner-field-label">目的地</span>
                <DestinationTokenField
                  values={destinations}
                  queries={destinationQueries}
                  onChange={(values, queries) => updateDestinationField(values, queries)}
                />
              </div>
            </div>
          </section>
          <section className="travel-intake-section">
            <div className="travel-intake-section-title">
              <span>02</span>
              <h2>什么时候，和谁一起</h2>
            </div>
            <DateRangePicker
              start={draft.start_date ?? ""}
              end={draft.end_date ?? ""}
              onChange={(start_date, end_date) =>
                setDraft((value) => ({ ...value, start_date, end_date }))
              }
            />
            {draft.duration_days && !draft.start_date && (
              <p className="travel-intake-hint">
                你希望玩 {draft.duration_days} 天，选好日期后就能安排。
              </p>
            )}
            <div className="travel-intake-party">
              {(["adults", "children"] as const).map((key) => (
                <div key={key}>
                  <span>{key === "adults" ? "成人" : "儿童"}</span>
                  <button
                    type="button"
                    aria-label={`减少${key === "adults" ? "成人" : "儿童"}`}
                    disabled={(party?.[key] ?? 0) <= (key === "adults" ? 1 : 0)}
                    onClick={() =>
                      setDraft((value) => ({
                        ...value,
                        party: {
                          adults: 1,
                          children: 0,
                          elderly_companions: false,
                          accessibility_required: false,
                          ...value.party,
                          [key]: Math.max(
                            key === "adults" ? 1 : 0,
                            (value.party?.[key] ?? 0) - 1,
                          ),
                        },
                      }))
                    }
                  >
                    <Minus size={14} />
                  </button>
                  <strong>{party?.[key] ?? "—"}</strong>
                  <button
                    type="button"
                    aria-label={`增加${key === "adults" ? "成人" : "儿童"}`}
                    onClick={() =>
                      setDraft((value) => ({
                        ...value,
                        party: {
                          adults: 1,
                          children: 0,
                          elderly_companions: false,
                          accessibility_required: false,
                          ...value.party,
                          [key]: Math.min(20, (value.party?.[key] ?? 0) + 1),
                        },
                      }))
                    }
                  >
                    <Plus size={14} />
                  </button>
                </div>
              ))}
              {!party && (
                <button
                  type="button"
                  onClick={() =>
                    setDraft((value) => ({
                      ...value,
                      party: {
                        adults: 1,
                        children: 0,
                        elderly_companions: false,
                        accessibility_required: false,
                      },
                    }))
                  }
                >
                  我一个人旅行
                </button>
              )}
            </div>
          </section>
          {questions.length > 0 && (
            <section className="travel-intake-section">
              <div className="travel-intake-section-title">
                <span>03</span>
                <h2>再确认一点</h2>
              </div>
              {questions
                .filter((item) => item.id !== activeQuestion?.id)
                .map((item) => {
                  const answer = answers.find(
                    (value) => value.question_id === item.id,
                  );
                  if (!answer) return null;
                  return (
                    <button
                      type="button"
                      key={item.id}
                      className="travel-intake-answer"
                      onClick={() => {
                        setEditingQuestion(item.id);
                        setFreeText(answer.supplement);
                      }}
                    >
                      <Check size={14} />
                      <span>
                        {item.question}
                        <strong>
                          {[
                            ...item.options
                              .filter((option) =>
                                answer.selected_option_ids.includes(option.id),
                              )
                              .map((option) => option.label),
                            answer.supplement,
                          ]
                            .filter(Boolean)
                            .join("；")}
                        </strong>
                      </span>
                      <span>修改</span>
                    </button>
                  );
                })}
              {activeQuestion && (
                <div ref={questionRef} tabIndex={-1} className="travel-intake-question">
                  <p>{activeQuestion.question}</p>
                  {activeQuestion.options.some((option) => option.id === 'sensible_default') && (
                    <p className="travel-intake-default-hint">
                      不确定时可以选择「按合理默认安排，不再补充」，我们会按常规节奏继续，不再重复询问。
                    </p>
                  )}
                  <div>
                    {activeQuestion.options.map((option) => (
                      <button
                        type="button"
                        data-default-option={option.id === 'sensible_default' ? 'true' : undefined}
                        aria-pressed={
                          activeAnswer?.selected_option_ids.includes(
                            option.id,
                          ) ?? false
                        }
                        key={option.id}
                        onClick={() => answerQuestion(option.id)}
                      >
                        {option.label}
                      </button>
                    ))}
                  </div>
                  <div className="travel-intake-free">
                    <input
                      aria-label="补充回答"
                      placeholder="也可以直接说说你的想法"
                      value={freeText}
                      onChange={(event) => setFreeText(event.target.value)}
                      maxLength={500}
                    />
                    <button
                      type="button"
                      aria-label="确认回答"
                      disabled={
                        !freeText.trim() &&
                        !activeAnswer?.selected_option_ids.length
                      }
                      onClick={() => answerQuestion()}
                    >
                      <ArrowRight size={16} />
                    </button>
                  </div>
                </div>
              )}
            </section>
          )}
          <section className="travel-intake-section">
            <button
              type="button"
              className="travel-intake-disclosure"
              aria-expanded={detailsOpen}
              onClick={() => setDetailsOpen((value) => !value)}
            >
              旅行偏好与其他补充
              <ChevronDown size={16} />
            </button>
            {detailsOpen && (
              <div className="travel-intake-details">
                {config && (
                  <div className="travel-intake-styles">
                    {config.primary_styles.map((item) => (
                      <button
                        type="button"
                        key={item.id}
                        aria-pressed={style?.primary === item.label}
                        onClick={() =>
                          setDraft((value) => ({
                            ...value,
                            style: {
                              primary: item.label,
                              secondary_interests:
                                value.style?.secondary_interests ?? [],
                              source: "current",
                            },
                          }))
                        }
                      >
                        {item.label}
                      </button>
                    ))}
                  </div>
                )}
                <textarea
                  aria-label="其他旅行要求"
                  value={additional}
                  onChange={(event) => setAdditional(event.target.value)}
                  placeholder="例如：尽量住在交通方便的地方，每天留一点自由时间"
                  maxLength={1000}
                  rows={3}
                />
              </div>
            )}
          </section>
        </div>
        {!inline && <aside className="travel-intake-summary">
          <p className="travel-intake-eyebrow">这趟旅行</p>
          <blockquote>{intake.raw_input}</blockquote>
          {(intake.recognized_requirements ?? []).length > 0 && (
            <ul>
              {intake.recognized_requirements!.map((item) => (
                <li key={item}>
                  <Check size={13} />
                  {item}
                </li>
              ))}
            </ul>
          )}
          <dl>
            <div>
              <dt>出发</dt>
              <dd>{origin?.name ?? "待确认"}</dd>
            </div>
            <div>
              <dt>目的地</dt>
              <dd>
                {destinations
                  .map((place) => place?.name ?? "待确认")
                  .join("、")}
              </dd>
            </div>
            <div>
              <dt>时间</dt>
              <dd>
                {draft.start_date && draft.end_date
                  ? `${draft.start_date} — ${draft.end_date}`
                  : "待确认"}
              </dd>
            </div>
            <div>
              <dt>同行</dt>
              <dd>
                {party
                  ? `${party.adults} 位成人${party.children ? ` · ${party.children} 位儿童` : ""}`
                  : "待确认"}
              </dd>
            </div>
            {draft.budget_text && (
              <div>
                <dt>预算</dt>
                <dd>{draft.budget_text}</dd>
              </div>
            )}
            <div>
              <dt>节奏</dt>
              <dd>
                {style?.primary ?? "经典均衡"}
                {style?.source === "suggested" ? "（建议，可修改）" : ""}
              </dd>
            </div>
          </dl>
        </aside>}
      </div>
      <footer className="travel-intake-footer">
        <span role="status">
          {saveState === "saving"
            ? "正在保存…"
            : saveState === "error"
              ? "保存未完成，开始前会再次保存"
              : "旅行草稿已保留，可随时修改"}
        </span>
        {error && <p ref={errorRef} tabIndex={-1} role="alert">{error}</p>}
        <Button
          size="lg"
          disabled={submitting || state.isStreaming}
          onClick={() => void start()}
        >
          {submitting ? (
            <Loader2 size={16} className="animate-spin" />
          ) : (
            <ArrowRight size={16} />
          )}
          确认信息并开始规划
        </Button>
      </footer>
    </m.section>
  );
};
