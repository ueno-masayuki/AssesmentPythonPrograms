/* pygrader WebUI (ビルド不要の素のJS) */

"use strict";

/* ---------- 共通 ---------- */

function $(id) { return document.getElementById(id); }

function showStatus(message, kind) {
  const el = $("status");
  if (!el) return;
  el.textContent = message;
  el.className = "notice " + (kind || "info");
  el.hidden = false;
  if (kind === "ok") setTimeout(() => { el.hidden = true; }, 4000);
  window.scrollTo({ top: 0, behavior: "smooth" });
}

async function postJSON(url, body) {
  const res = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.detail || `エラー (${res.status})`);
  return data;
}

/* ---------- 課題編集ページ ---------- */

function initEditPage() {
  const a = window.PYGRADER.assignment;
  $("f-title").value = a.title || "";
  $("f-description").value = a.description || "";
  $("f-expected").value = a.expected_filename || "";
  $("f-maxgrade").value = a.max_grade ?? 100;
  $("f-timeout").value = a.tests?.timeout ?? 5;
  $("f-llm-enabled").checked = a.llm?.enabled !== false;
  $("f-similarity").checked = a.similarity_check !== false;
  $("f-llm-model").value = a.llm?.model || "claude-sonnet-5-5";
  $("f-model-answer").value = a.model_answer || "";

  for (const r of a.rubric || []) addRubricRow(r);
  for (const c of a.tests?.cases || []) addTestRow(c);

  $("btn-save").addEventListener("click", saveAssignment);
  $("btn-check").addEventListener("click", runCheck);
  $("btn-normalize").addEventListener("click", normalizePoints);
  for (const btn of document.querySelectorAll("button.propose")) {
    btn.addEventListener("click", () => propose(btn.dataset.target, btn));
  }
  // ルーブリックやテストの編集に追従して、ドロップダウン・合計・評価方法を更新
  document.querySelector("#rubric-table").addEventListener("input", refreshRubricState);
  document.querySelector("#tests-table").addEventListener("change", refreshRubricState);
  $("f-maxgrade").addEventListener("input", refreshRubricState);
  refreshRubricState();
}

/* 現在のルーブリック行から {id, name} の一覧を得る */
function currentCriteria() {
  const out = [];
  for (const tr of document.querySelectorAll("#rubric-table tbody tr")) {
    const id = tr.querySelector(".r-id").value.trim();
    if (id) out.push({ id, name: tr.querySelector(".r-name").value.trim() || id });
  }
  return out;
}

function refreshRubricState() {
  const criteria = currentCriteria();
  // テスト行の「評価基準」ドロップダウンを更新（選択値は維持）
  for (const sel of document.querySelectorAll("#tests-table .t-criterion")) {
    const cur = sel.value;
    sel.replaceChildren();
    for (const c of criteria) {
      const opt = document.createElement("option");
      opt.value = c.id;
      opt.textContent = `${c.name} (${c.id})`;
      sel.appendChild(opt);
    }
    if (criteria.some(c => c.id === cur)) sel.value = cur;
  }
  // 各基準の評価方法（自動テスト / AI評価）表示を更新
  const linked = new Set(
    [...document.querySelectorAll("#tests-table .t-criterion")].map(s => s.value));
  for (const tr of document.querySelectorAll("#rubric-table tbody tr")) {
    const id = tr.querySelector(".r-id").value.trim();
    tr.querySelector(".r-method").textContent = linked.has(id) ? "🧪 自動テスト" : "🤖 AI評価";
  }
  // 配点合計の表示
  const total = [...document.querySelectorAll("#rubric-table .r-points")]
    .reduce((s, el) => s + (parseFloat(el.value) || 0), 0);
  const max = parseFloat($("f-maxgrade").value) || 0;
  const el = $("points-total");
  if (currentCriteria().length === 0) {
    el.textContent = "";
    return;
  }
  const ok = Math.abs(total - max) < 0.01;
  el.textContent = ok
    ? `配点合計: ${total} / 最大評点 ${max} ✓`
    : `配点合計: ${total} / 最大評点 ${max} ⚠ 一致していません（保存できません）`;
  el.className = "points-total " + (ok ? "ok" : "warn");
}

/* 配点を比例スケールして合計=最大評点にする */
function normalizePoints() {
  const inputs = [...document.querySelectorAll("#rubric-table .r-points")];
  const max = parseFloat($("f-maxgrade").value) || 0;
  if (!inputs.length || max <= 0) return;
  const points = inputs.map(el => parseFloat(el.value) || 0);
  const cur = points.reduce((s, p) => s + p, 0);
  let scaled = cur > 0 ? points.map(p => p * max / cur) : points.map(() => max / points.length);
  let rounded = scaled.map(p => Math.max(1, Math.round(p)));
  let diff = Math.round(max - rounded.reduce((s, p) => s + p, 0));
  const order = [...rounded.keys()].sort((i, j) => rounded[j] - rounded[i]);
  while (diff !== 0) {
    let moved = false;
    for (const i of order) {
      if (diff > 0) { rounded[i] += 1; diff -= 1; moved = true; }
      else if (rounded[i] > 1) { rounded[i] -= 1; diff += 1; moved = true; }
      if (diff === 0) break;
    }
    if (!moved) break;
  }
  inputs.forEach((el, i) => { el.value = rounded[i]; });
  refreshRubricState();
}

function addTestRow(c) {
  c = c || {};
  const tbody = document.querySelector("#tests-table tbody");
  const tr = document.createElement("tr");
  tr.innerHTML = `
    <td><input class="t-name" value=""></td>
    <td><select class="t-criterion"></select></td>
    <td><textarea class="t-stdin"></textarea></td>
    <td><textarea class="t-expected-stdout"></textarea></td>
    <td><select class="t-match">
      <option>trim</option><option>exact</option><option>whitespace</option><option>regex</option>
    </select></td>
    <td><input class="t-function" placeholder="(stdinテストなら空)"></td>
    <td><input class="t-args" placeholder='[[1,2,3]]'></td>
    <td><input class="t-expected" placeholder="2.0"></td>
    <td><input class="t-weight" type="number" min="0.1" step="0.1" value="1"></td>
    <td><button class="small danger" onclick="this.closest('tr').remove(); refreshRubricState()">✕</button></td>`;
  tr.querySelector(".t-name").value = c.name || "";
  tr.querySelector(".t-stdin").value = c.stdin || "";
  tr.querySelector(".t-expected-stdout").value = c.expected_stdout || "";
  tr.querySelector(".t-match").value = c.match || "trim";
  tr.querySelector(".t-function").value = c.function || "";
  tr.querySelector(".t-args").value = c.args !== undefined && c.function ? JSON.stringify(c.args) : "";
  tr.querySelector(".t-expected").value = c.expected !== undefined && c.function ? JSON.stringify(c.expected) : "";
  tr.querySelector(".t-weight").value = c.weight ?? 1;
  tbody.appendChild(tr);
  // ドロップダウンに現在の基準を反映し、指定があれば選択（なければ先頭基準）
  const sel = tr.querySelector(".t-criterion");
  for (const cr of currentCriteria()) {
    const opt = document.createElement("option");
    opt.value = cr.id;
    opt.textContent = `${cr.name} (${cr.id})`;
    sel.appendChild(opt);
  }
  if (c.criterion) sel.value = c.criterion;
  if (typeof refreshRubricState === "function") refreshRubricState();
}

function addRubricRow(r) {
  r = r || {};
  const tbody = document.querySelector("#rubric-table tbody");
  const tr = document.createElement("tr");
  tr.innerHTML = `
    <td><input class="r-id" placeholder="readability"></td>
    <td><input class="r-name"></td>
    <td><input class="r-points" type="number" min="1" step="1" value="10"></td>
    <td class="r-method muted"></td>
    <td><input class="r-desc"></td>
    <td><button class="small danger" onclick="this.closest('tr').remove(); refreshRubricState()">✕</button></td>`;
  tr.querySelector(".r-id").value = r.id || "";
  tr.querySelector(".r-name").value = r.name || "";
  tr.querySelector(".r-points").value = r.points ?? 10;
  tr.querySelector(".r-desc").value = r.description || "";
  tbody.appendChild(tr);
  if (typeof refreshRubricState === "function") refreshRubricState();
}

function collectAssignment() {
  const cases = [];
  for (const tr of document.querySelectorAll("#tests-table tbody tr")) {
    const name = tr.querySelector(".t-name").value.trim();
    const fn = tr.querySelector(".t-function").value.trim();
    const weight = parseFloat(tr.querySelector(".t-weight").value) || 1;
    const criterion = tr.querySelector(".t-criterion").value || null;
    if (fn) {
      let args = [], expected = null;
      const argsText = tr.querySelector(".t-args").value.trim();
      const expText = tr.querySelector(".t-expected").value.trim();
      try { if (argsText) args = JSON.parse(argsText); }
      catch { throw new Error(`テスト「${name || fn}」の args がJSONとして不正です`); }
      try { if (expText) expected = JSON.parse(expText); }
      catch { throw new Error(`テスト「${name || fn}」の期待値がJSONとして不正です`); }
      cases.push({ name: name || fn, function: fn, args, expected, weight, criterion });
    } else {
      const expectedStdout = tr.querySelector(".t-expected-stdout").value;
      if (!name && !expectedStdout) continue; // 空行は無視
      cases.push({
        name: name || `テスト${cases.length + 1}`,
        stdin: tr.querySelector(".t-stdin").value,
        expected_stdout: expectedStdout,
        match: tr.querySelector(".t-match").value,
        weight,
        criterion,
      });
    }
  }
  const rubric = [];
  for (const tr of document.querySelectorAll("#rubric-table tbody tr")) {
    const id = tr.querySelector(".r-id").value.trim();
    const name = tr.querySelector(".r-name").value.trim();
    if (!id && !name) continue;
    rubric.push({
      id: id || `criterion${rubric.length + 1}`,
      name: name || id,
      points: parseFloat(tr.querySelector(".r-points").value) || 1,
      description: tr.querySelector(".r-desc").value.trim(),
    });
  }
  return {
    title: $("f-title").value.trim(),
    description: $("f-description").value,
    expected_filename: $("f-expected").value.trim() || null,
    max_grade: parseFloat($("f-maxgrade").value) || 100,
    tests: { timeout: parseFloat($("f-timeout").value) || 5, cases },
    rubric,
    model_answer: $("f-model-answer").value,
    llm: { model: $("f-llm-model").value.trim(), enabled: $("f-llm-enabled").checked },
    similarity_check: $("f-similarity").checked,
  };
}

async function saveAssignment() {
  let data;
  try { data = collectAssignment(); }
  catch (e) { showStatus(e.message, "error"); return; }
  try {
    await postJSON(`/api/assignments/${window.PYGRADER.slug}/save`, data);
    showStatus("保存しました", "ok");
  } catch (e) {
    showStatus(`保存できません: ${e.message}`, "error");
  }
}

async function propose(target, btn) {
  let data;
  try { data = collectAssignment(); }
  catch (e) { showStatus(e.message, "error"); return; }
  const original = btn.textContent;
  btn.disabled = true;
  btn.textContent = "生成中…（数十秒かかることがあります）";
  try {
    const res = await postJSON(`/api/assignments/${window.PYGRADER.slug}/propose`,
                               { target, assignment: data });
    if (target === "model_answer") {
      $("f-model-answer").value = res.code;
      const note = $("proposal-note");
      let text = `提案の説明: ${res.explanation}`;
      if (res.test_results) {
        const ok = res.test_results.filter(r => r.status === "pass").length;
        text += `\n登録済みテストでの検証: ${ok}/${res.test_results.length} 件合格`;
        for (const r of res.test_results.filter(r => r.status !== "pass")) {
          text += `\n  ✘ ${r.name}: ${r.detail || r.status}`;
        }
      }
      note.textContent = text;
      note.hidden = false;
      showStatus("回答例を挿入しました。内容を確認・修正して保存してください。", "ok");
    } else if (target === "rubric") {
      document.querySelector("#rubric-table tbody").replaceChildren();
      for (const c of res.criteria) addRubricRow(c);
      showStatus("ルーブリック案を挿入しました。内容を確認・修正して保存してください。", "ok");
    } else if (target === "tests") {
      for (const c of res.cases) addTestRow(c);
      showStatus("テストケース案を末尾に追加しました。内容を確認・修正して保存してください。", "ok");
    }
  } catch (e) {
    showStatus(`提案を生成できません: ${e.message}`, "error");
  } finally {
    btn.disabled = false;
    btn.textContent = original;
  }
}

async function runCheck() {
  let data;
  try { data = collectAssignment(); }
  catch (e) { showStatus(e.message, "error"); return; }
  const box = $("check-results");
  box.hidden = false;
  box.innerHTML = "<p>実行中…</p>";
  try {
    const res = await postJSON(`/api/assignments/${window.PYGRADER.slug}/check`,
                               { assignment: data });
    const rows = res.results.map(r => {
      const cls = r.status === "pass" ? "status-pass" : "status-fail";
      const mark = r.status === "pass" ? "✔ 合格" : `✘ ${r.status}`;
      return `<tr><td>${escapeHtml(r.name)}</td><td class="${cls}">${mark}</td>` +
             `<td class="small-text">${escapeHtml(r.detail || "")}</td></tr>`;
    }).join("");
    box.innerHTML = `<table class="list"><thead><tr><th>テスト</th><th>結果</th><th>詳細</th></tr></thead>` +
                    `<tbody>${rows}</tbody></table>`;
  } catch (e) {
    box.innerHTML = `<div class="notice error">${escapeHtml(e.message)}</div>`;
  }
}

function escapeHtml(s) {
  return String(s).replace(/[&<>"']/g,
    ch => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[ch]));
}

/* ---------- 採点結果ページ（進捗ポーリング） ---------- */

function pollRunStatus(runId) {
  const bar = $("progress-bar");
  const text = $("progress-text");
  const timer = setInterval(async () => {
    try {
      const res = await fetch(`/api/runs/${runId}/status`);
      if (!res.ok) throw new Error(`status ${res.status}`);
      const s = await res.json();
      if (s.status === "done") {
        clearInterval(timer);
        location.reload();
      } else if (s.status === "error") {
        clearInterval(timer);
        text.textContent = `エラーが発生しました: ${s.error || ""}`;
        text.className = "notice error";
      } else {
        if (s.total > 0) {
          bar.max = s.total;
          bar.value = s.done;
          text.textContent = `${s.done} / ${s.total} 人目を採点中: ${s.current}`;
        }
      }
    } catch {
      /* 一時的な失敗は次のポーリングで回復 */
    }
  }, 1500);
}
