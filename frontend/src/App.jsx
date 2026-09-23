import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { ApiError, solveMessages, analyzeOrder } from "./api.js";

const MIN_ROWS = 2;
const MAX_ROWS = 18;
let uidSeq = 0;
const uid = () => `row-${++uidSeq}`;
const EMPTY_ROW = () => ({ key: uid(), id: "", C: "", T: "", D: "", J: "0" });

const SAMPLE = [
  { id: "TM_HK_01", C: 2, T: 20, D: 20, J: 1 },
  { id: "TM_ATT_02", C: 4, T: 50, D: 40, J: 2 },
  { id: "TM_PL_03", C: 6, T: 100, D: 80, J: 0 },
  { id: "TM_CMD_04", C: 1, T: 25, D: 10, J: 0 },
];

// Give every editable row a stable identity so React state survives reorder/delete.
const toRows = (arr) =>
  arr.map((m) => ({
    key: uid(),
    id: String(m.id),
    C: String(m.C),
    T: String(m.T),
    D: String(m.D),
    J: String(m.J ?? 0),
  }));

// ---------- import / export ----------

function parseImport(text) {
  const trimmed = text.trim();
  if (!trimmed) throw new Error("导入内容为空");
  if (trimmed.startsWith("[") || trimmed.startsWith("{")) {
    const data = JSON.parse(trimmed);
    const arr = Array.isArray(data) ? data : data.messages;
    if (!Array.isArray(arr)) throw new Error("JSON 需为消息数组或含 messages 字段");
    return toRows(
      arr.map((o) => ({
        id: o.id ?? "",
        C: o.C ?? "",
        T: o.T ?? "",
        D: o.D ?? "",
        J: o.J ?? 0,
      }))
    );
  }
  // CSV / TSV: id C T D [J], header row auto-detected.
  const lines = trimmed
    .split(/\r?\n/)
    .map((l) => l.trim())
    .filter(Boolean)
    .map((l) => l.split(/[,;\t]|\s+/).filter((s) => s !== ""));
  let startIdx = 0;
  if (/[A-Za-z]/.test(lines[0][0] || "") && Number.isNaN(Number(lines[0][1]))) {
    startIdx = 1;
  }
  return toRows(
    lines.slice(startIdx).map((cols) => {
      if (cols.length < 4) throw new Error("每行至少需要 编号 C T D 四列");
      return {
        id: cols[0],
        C: cols[1],
        T: cols[2],
        D: cols[3],
        J: cols[4] ?? "0",
      };
    })
  );
}

// ---------- 422 field indexing ----------

function useFieldErrors() {
  // key `${rowIndex}.${field}` -> message; also global messages without row.
  const [map, setMap] = useState({});
  const [global, setGlobal] = useState([]);

  const ingest = useCallback((detail) => {
    const next = {};
    const globals = [];
    for (const e of detail) {
      const loc = e.loc || [];
      const rowIdx = loc.find((v) => v === "messages") >= 0
        ? loc[loc.indexOf("messages") + 1]
        : undefined;
      const field = loc.length && typeof loc[loc.length - 1] === "string"
        ? loc[loc.length - 1]
        : undefined;
      if (typeof rowIdx === "number" && field) {
        next[`${rowIdx}.${field}`] = e.msg;
      } else {
        globals.push(e.msg);
      }
    }
    setMap(next);
    setGlobal(globals);
  }, []);

  const clear = useCallback(() => {
    setMap({});
    setGlobal([]);
  }, []);

  return { map, global, ingest, clear };
}

// ---------- small UI atoms ----------

function Badge({ miss }) {
  return miss ? (
    <span className="badge badge-miss">超期</span>
  ) : (
    <span className="badge badge-ok">可行</span>
  );
}

function ObjectivePanel({ data }) {
  const o = data.objective;
  return (
    <div className="objective">
      <div>
        <span className="obj-label">超期消息数</span>
        <span className={`obj-value ${o.deadline_misses ? "warn" : ""}`}>
          {o.deadline_misses}
        </span>
      </div>
      <div>
        <span className="obj-label">Σ min(Rᵢ, Dᵢ+1)</span>
        <span className="obj-value">{o.sum_capped_response_times}</span>
      </div>
      <div className="obj-note">{data.tie_break}</div>
    </div>
  );
}

function TrajectoryTable({ result }) {
  return (
    <table className="trace">
      <thead>
        <tr>
          <th>迭代 k</th>
          <th>r(k)</th>
          <th>高优先级干扰 Σ ceil((r+Jₕ)/Tₕ)·Cₕ</th>
        </tr>
      </thead>
      <tbody>
        {result.trajectory.map((s) => (
          <tr
            key={s.step}
            className={
              s.step === 0
                ? "trace-r0"
                : result.deadline_miss && s.step === result.trajectory.length - 1
                ? "trace-miss"
                : ""
            }
          >
            <td>{s.step}</td>
            <td className="num">{s.r.toLocaleString()}</td>
            <td>
              {s.step === 0 ? (
                <em className="muted">r(0) = J + C + B = {s.r}</em>
              ) : s.terms.length === 0 ? (
                <em className="muted">无干扰，定点确认</em>
              ) : (
                <ul className="terms">
                  {s.terms.map((t) => (
                    <li key={t.id}>
                      <strong>{t.id}</strong>：ceil((r+{t.J})/{t.T}) × {t.C} ={" "}
                      {t.jobs} × {t.C} = {t.amount.toLocaleString()}
                    </li>
                  ))}
                  <li className="terms-sum">合计干扰：{s.interference.toLocaleString()}</li>
                </ul>
              )}
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

function MessageCard({ result, order, onMove }) {
  const idx = order.indexOf(result.id);
  return (
    <details className="card" open={result.deadline_miss}>
      <summary>
        <span className="card-pos">#{result.position}</span>
        <span className="card-id">{result.id}</span>
        <Badge miss={result.deadline_miss} />
        <span className="card-r">
          R = {result.response_time.toLocaleString()} / D = {result.D.toLocaleString()}
        </span>
        {onMove && (
          <span className="move-buttons" onClick={(e) => e.stopPropagation()}>
            <button disabled={idx <= 0} onClick={() => onMove(result.id, -1)} title="提高优先级">
              ↑
            </button>
            <button
              disabled={idx === -1 || idx >= order.length - 1}
              onClick={() => onMove(result.id, 1)}
              title="降低优先级"
            >
              ↓
            </button>
          </span>
        )}
      </summary>
      <div className="card-body">
        <div className="kv-grid">
          <div><span>C 传输时长</span><b>{result.C.toLocaleString()}</b></div>
          <div><span>T 周期</span><b>{result.T.toLocaleString()}</b></div>
          <div><span>D 截止期</span><b>{result.D.toLocaleString()}</b></div>
          <div><span>J 抖动</span><b>{result.J.toLocaleString()}</b></div>
          <div>
            <span>B 阻塞</span>
            <b>
              {result.blocking.toLocaleString()}
              {result.blocking_from_id && (
                <em className="muted">（来自最低优先级的 {result.blocking_from_id}）</em>
              )}
            </b>
          </div>
          <div>
            <span>高优先级消息</span>
            <b>
              {result.higher_priority_ids.length
                ? result.higher_priority_ids.join(" → ")
                : "无"}
            </b>
          </div>
        </div>
        <TrajectoryTable result={result} />
        <p className={`criterion ${result.deadline_miss ? "miss-text" : "ok-text"}`}>
          判据：{result.criterion}
        </p>
      </div>
    </details>
  );
}

// ---------- main app ----------

export default function App() {
  const [rows, setRows] = useState(() => toRows(SAMPLE));
  const [result, setResult] = useState(null); // {mode, data}
  const [busy, setBusy] = useState(false);
  const [importOpen, setImportOpen] = useState(false);
  const [importText, setImportText] = useState("");
  const [importErr, setImportErr] = useState("");
  const [analyzeOrderIds, setAnalyzeOrderIds] = useState(null);
  const { map: fieldErrors, global, ingest, clear } = useFieldErrors();

  const reqSeq = useRef(0);
  const abortRef = useRef(null);

  // Cancel an in-flight call and invalidate any late response, but keep the
  // current draft (rows and working order) untouched.
  const cancelInflight = useCallback(() => {
    if (abortRef.current) {
      abortRef.current.abort();
      abortRef.current = null;
    }
    reqSeq.current += 1;
  }, []);

  // Any draft edit retires the previous result entirely.
  const retire = useCallback(() => {
    cancelInflight();
    setBusy(false);
    setResult(null);
    setAnalyzeOrderIds(null);
    clear();
  }, [cancelInflight, clear]);

  const updateRow = (i, field, value) => {
    retire();
    setRows((rs) => rs.map((r, k) => (k === i ? { ...r, [field]: value } : r)));
  };

  const addRow = () => {
    if (rows.length >= MAX_ROWS) return;
    retire();
    setRows((rs) => [...rs, EMPTY_ROW()]);
  };

  const removeRow = (i) => {
    if (rows.length <= MIN_ROWS) return;
    retire();
    setRows((rs) => rs.filter((_, k) => k !== i));
  };

  const loadSample = () => {
    retire();
    setRows(toRows(SAMPLE));
  };

  const doImport = () => {
    try {
      const parsed = parseImport(importText);
      if (parsed.length < MIN_ROWS || parsed.length > MAX_ROWS) {
        throw new Error(`消息数量必须在 ${MIN_ROWS} 至 ${MAX_ROWS} 条之间`);
      }
      retire();
      setRows(parsed);
      setImportOpen(false);
      setImportText("");
      setImportErr("");
    } catch (e) {
      setImportErr(e.message);
    }
  };

  const runRequest = useCallback(
    async (mode, callFactory) => {
      // Keep the working draft; only supersede an earlier request.
      cancelInflight();
      setResult(null);
      clear();
      const seq = ++reqSeq.current;
      const controller = new AbortController();
      abortRef.current = controller;
      setBusy(true);
      try {
        const data = await callFactory(controller.signal);
        // Stale-response guard: only the latest request may land.
        if (seq !== reqSeq.current) return;
        setResult({ mode, data });
        if (mode === "solve") setAnalyzeOrderIds([...data.order]);
      } catch (err) {
        if (err.name === "AbortError" || seq !== reqSeq.current) return;
        if (err instanceof ApiError && err.status === 422) {
          ingest(err.detail);
        } else {
          ingest([{ loc: [], msg: err instanceof ApiError ? err.detail?.[0]?.msg : String(err) }]);
        }
      } finally {
        if (seq === reqSeq.current) {
          setBusy(false);
          abortRef.current = null;
        }
      }
    },
    [ingest, cancelInflight, clear]
  );

  const onSolve = () => {
    setAnalyzeOrderIds(null); // a fresh solution replaces any working order
    runRequest("solve", (signal) => solveMessages(serializeRows(rows), signal));
  };

  const onAnalyze = () => {
    if (!analyzeOrderIds) return;
    runRequest("analyze", (signal) =>
      analyzeOrder(serializeRows(rows), analyzeOrderIds, signal)
    );
  };

  const moveId = (id, dir) => {
    // Reordering is a draft change too: cancel any in-flight call, invalidate
    // its (possibly late) response and retire the previous verdict, while
    // keeping the working order itself.
    cancelInflight();
    setBusy(false);
    setResult(null);
    clear();
    setAnalyzeOrderIds((ords) => {
      const next = [...ords];
      const i = next.indexOf(id);
      const j = i + dir;
      if (i < 0 || j < 0 || j >= next.length) return ords;
      [next[i], next[j]] = [next[j], next[i]];
      return next;
    });
  };

  const orderShown = result ? result.data.order : analyzeOrderIds;

  return (
    <div className="page">
      <header>
        <h1>卫星固定优先级遥测总线 · 可调度性分析台</h1>
        <p className="subtitle">
          对全部 {MAX_ROWS}! 种固定优先级顺序做精确枚举级子集 DP 寻优，依次最小化
          <b> 超期消息数</b>、<b> Σmin(Rᵢ,Dᵢ+1)</b>，同分取编号序列字典序最小者。
        </p>
      </header>

      <section className="panel">
        <div className="panel-head">
          <h2>消息集（{rows.length} / {MAX_ROWS}）</h2>
          <div className="toolbar">
            <button onClick={loadSample}>载入示例</button>
            <button onClick={() => setImportOpen((v) => !v)}>
              {importOpen ? "收起导入" : "导入消息"}
            </button>
            <button onClick={addRow} disabled={rows.length >= MAX_ROWS}>
              + 新增
            </button>
          </div>
        </div>

        {importOpen && (
          <div className="import-box">
            <p className="muted">
              支持 JSON 数组（<code>{'[{id,C,T,D,J}]'}</code>）或每行一条的
              CSV/TSV：<code>编号 C T D [J]</code>，可含表头。
            </p>
            <textarea
              rows={5}
              value={importText}
              onChange={(e) => setImportText(e.target.value)}
              placeholder={'TM01,2,20,20,1\nTM02,4,50,40,2'}
            />
            {importErr && <p className="miss-text">{importErr}</p>}
            <button onClick={doImport}>导入并替换当前消息集</button>
          </div>
        )}

        <div className="table-wrap">
          <table className="editor">
            <thead>
              <tr>
                <th>#</th>
                <th>唯一编号</th>
                <th>C 传输时长</th>
                <th>T 周期</th>
                <th>D 截止期</th>
                <th>J 抖动</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {rows.map((r, i) => (
                <tr key={r.key} className={hasRowError(fieldErrors, i) ? "row-err" : ""}>
                  <td className="muted">{i + 1}</td>
                  <td>
                    <input
                      value={r.id}
                      onChange={(e) => updateRow(i, "id", e.target.value)}
                      className={fieldErrors[`${i}.id`] ? "input-err" : ""}
                    />
                  </td>
                  {["C", "T", "D", "J"].map((f) => (
                    <td key={f}>
                      <input
                        value={r[f]}
                        inputMode="numeric"
                        onChange={(e) => updateRow(i, f, e.target.value)}
                        className={fieldErrors[`${i}.${f}`] ? "input-err" : ""}
                      />
                      {fieldErrors[`${i}.${f}`] && (
                        <div className="field-msg">{fieldErrors[`${i}.${f}`]}</div>
                      )}
                    </td>
                  ))}
                  <td>
                    <button
                      className="del"
                      onClick={() => removeRow(i)}
                      disabled={rows.length <= MIN_ROWS}
                      title="删除该行"
                    >
                      ✕
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        {global.length > 0 && (
          <ul className="global-err">
            {global.map((m, i) => (
              <li key={i}>{m}</li>
            ))}
          </ul>
        )}

        <div className="constraints muted">
          约束：1 ≤ C ≤ D ≤ T ≤ 10⁹，0 ≤ J ≤ D−C，编号 2–18 条且唯一。
          编辑任意输入即撤下旧结果；迟到的响应不会覆盖更新后的草稿。
        </div>

        <div className="actions">
          <button className="primary" onClick={onSolve} disabled={busy}>
            {busy ? "求解中…（对 2^18 状态空间做精确分析）" : "求全局最优优先级顺序"}
          </button>
        </div>
      </section>

      {result && result.mode === "solve" && (
        <section className="panel">
          <div className="panel-head">
            <h2>求解结果</h2>
            <span className="muted">
              {result.data.search.total_permutations.toLocaleString()} 个排列中的最优
              （评估状态 {result.data.search.states_evaluated.toLocaleString()}，
              RTA 迭代 {result.data.search.rta_iterations.toLocaleString()} 次）
            </span>
          </div>
          <ObjectivePanel data={result.data} />
          <OrderStrip order={result.data.order} editable={false} />
        </section>
      )}

      {analyzeOrderIds && (
        <section className="panel">
          <div className="panel-head">
            <h2>顺序与逐条判据</h2>
            <div className="toolbar">
              <span className="muted">↑/↓ 调整后分析自定义顺序（左为高优先级）</span>
              <button className="primary small" onClick={onAnalyze} disabled={busy}>
                分析此顺序
              </button>
            </div>
          </div>
          <OrderStrip order={analyzeOrderIds} editable onMove={moveId} />
          {result && (
            <div className="cards">
              {result.data.results.map((r) => (
                <MessageCard
                  key={`${result.mode}-${r.id}`}
                  result={r}
                  order={orderShown}
                  onMove={result.mode === "analyze" ? moveId : null}
                />
              ))}
            </div>
          )}
          {!result && (
            <p className="muted">顺序已调整，点击「分析此顺序」查看阻塞、迭代轨迹与超期结论。</p>
          )}
        </section>
      )}
    </div>
  );
}

function serializeRows(rows) {
  return rows.map((r) => ({
    id: r.id.trim(),
    C: Number(r.C),
    T: Number(r.T),
    D: Number(r.D),
    J: r.J === "" || r.J == null ? 0 : Number(r.J),
  }));
}

function hasRowError(map, i) {
  return Object.keys(map).some((k) => k.startsWith(`${i}.`));
}

function OrderStrip({ order, editable, onMove }) {
  return (
    <ol className="order-strip">
      {order.map((id, i) => (
        <li key={id}>
          <span className="rank">{i + 1}</span>
          <span className="chip">{id}</span>
          {editable && onMove && (
            <span className="chip-move">
              <button disabled={i === 0} onClick={() => onMove(id, -1)}>↑</button>
              <button disabled={i === order.length - 1} onClick={() => onMove(id, 1)}>↓</button>
            </span>
          )}
          {i < order.length - 1 && <span className="arrow">→</span>}
        </li>
      ))}
    </ol>
  );
}
