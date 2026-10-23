"use strict";

const STATUS = {
  work: "מנקה עכשיו", pause: "בהפסקה", stop: "עצר ומחכה", charge: "בדרך לעמדה",
  charging_on_dock: "נטען בעמדה", charge_finish: "בעמדה, טעון", charging_with_wire: "נטען בכבל",
  sleep: "ישן", error: "צריך עזרה", relocate: "מחפש את הכיוון", updating: "מתעדכן",
  reserve_task_finished: "סיים ניקוי מתוזמן", charge_pause: "הטעינה נעצרה", none: "מחכה",
};
const LINK = {
  starting: "מתחבר לרובוט", connecting: "מתחבר לרובוט", lost: "הקשר נותק, מחפש אותו",
  offline: "הרובוט לא ברשת", no_key: "צריך חיבור ראשוני", no_key_offline: "הרובוט לא ברשת",
};
const ERRORS = {
  fix_dust: "פח האבק לא יושב במקום. דוחפים אותו עד הסוף.",
  fix_wheel_hang: "גלגל באוויר. הרובוט הורם או עלה על משהו.",
  fix_wheel_overload: "גלגל נתקע. בודקים שאין חוט או שטיח מתחתיו.",
  fix_side_brush_overload: "מברשת הצד נתקעה, בדרך כלל משיערות.",
  fix_roll_brush_overload: "המברשת הראשית נתקעה. מנקים ממנה שיערות.",
  fix_dust_engine: "בעיה במנוע היניקה.",
  fix_front_panel: "הפגוש הקדמי נתקע. לוחצים עליו כמה פעמים.",
  fix_drop_sensor: "חיישני הנפילה מלוכלכים, או שהוא על קצה מדרגה.",
  fix_low_battery: "הסוללה חלשה מדי. מחזירים אותו לעמדה.",
  fix_abnormal_posture: "הרובוט נטוי או תקוע. מניחים אותו ישר על הרצפה.",
  fix_edge_sensor: "חיישן הקיר מלוכלך. מנגבים אותו.",
  warn_low_battery: "סוללה חלשה, הוא חוזר להיטען.",
  warn_full_dust: "פח האבק מלא. מרוקנים אותו.",
  warn_low_water: "נגמרו המים במיכל.",
  warn_location_fail: "הרובוט איבד את הכיוון.",
};
const PARTS = { main_brush: "מברשת ראשית", side_brush: "מברשת צד", filter: "פילטר", mop: "מגב" };
const EVENTS = {
  online: "התחבר לרשת", offline: "נעלם מהרשת", error: "תקלה", consumable_reset: "הוחלף חלק",
  setup: "חיבור ראשוני", raw: "פקודת בדיקה",
  command: { start: "התחיל ניקוי", stop: "נעצר", pause: "הפסקה", dock: "נשלח הביתה" },
};
const MODE_NAME = { arc: "כל הבית", edge: "קירות", screw: "נקודה" };
const DAY = ["א׳", "ב׳", "ג׳", "ד׳", "ה׳", "ו׳", "ש׳"];
const RING = 2 * Math.PI * 148;

const $ = (id) => document.getElementById(id);
let snap = null;

function toast(text) {
  const t = $("toast");
  t.textContent = text;
  t.classList.add("on");
  clearTimeout(toast.timer);
  toast.timer = setTimeout(() => t.classList.remove("on"), 2600);
}

async function api(path, body) {
  const res = await fetch(path, body === undefined ? {} : {
    method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify(body),
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.error || res.statusText);
  return data;
}

function time(ts) {
  return new Date(ts * 1000).toLocaleTimeString("he-IL", { hour: "2-digit", minute: "2-digit" });
}
function dayLabel(ts) {
  const d = new Date(ts * 1000), today = new Date();
  const y = new Date(); y.setDate(today.getDate() - 1);
  if (d.toDateString() === today.toDateString()) return "היום";
  if (d.toDateString() === y.toDateString()) return "אתמול";
  return d.toLocaleDateString("he-IL", { weekday: "long", day: "numeric", month: "numeric" });
}

/* ---------- home ---------- */

function render() {
  if (!snap) return;
  const s = snap.state, online = s.online && s.link === "ok";
  const chip = $("chip");
  chip.className = "chip " + (online ? "on" : "off");
  $("chipText").textContent = online ? "מחובר בבית" : (LINK[s.link] || "לא מחובר");

  const pct = Number.isFinite(s.battery) ? s.battery : null;
  $("pctText").firstChild.textContent = pct === null ? "--" : String(pct);
  $("ring").style.strokeDashoffset = pct === null ? RING : RING * (1 - pct / 100);
  const lvl = pct === null ? "var(--soft)" : pct < 20 ? "var(--bad)" : pct < 50 ? "var(--mid)" : "var(--ok)";
  document.documentElement.style.setProperty("--lvl", lvl);
  $("robot").classList.toggle("working", s.status === "work");

  $("status").textContent = online ? (STATUS[s.status] || "מחכה") : (LINK[s.link] || "לא מחובר");
  const facts = [];
  if (online && ["work", "pause", "stop", "charge"].includes(s.status)) {
    facts.push(`<span><b>${s.work_time || 0}</b> דק׳</span>`, `<span><b>${s.area || 0}</b> מ״ר</span>`);
    if (MODE_NAME[s.mode]) facts.push(`<span>${MODE_NAME[s.mode]}</span>`);
  }
  if (online && s.mop === "on") facts.push("<span>מגב מחובר</span>");
  if (online && s.mop === "lack_water") facts.push("<span>המגב בלי מים</span>");
  $("facts").innerHTML = facts.join("");

  const err = s.error_desc && s.error_desc !== "no" ? s.error_desc : null;
  $("alert").classList.toggle("on", !!err);
  if (err) {
    $("alertTitle").textContent = s.error_type === "warning" ? "שימו לב" : "הרובוט צריך עזרה";
    $("alertText").textContent = ERRORS[err] || err;
  }

  const working = s.status === "work";
  const home = ["charge", "charging_on_dock", "charge_finish", "charging_with_wire"].includes(s.status);
  $("goBtn").disabled = !online || working;
  $("goBtn").textContent = s.status === "stop" || s.status === "pause" ? "המשך" : "נקה";
  $("stopBtn").disabled = !online || !["work", "charge"].includes(s.status);
  $("dockBtn").disabled = !online || home;

  for (const [group, key] of [["modes", "mode"], ["fan", "fan"], ["water", "water"]]) {
    for (const b of $(group).querySelectorAll("button")) {
      b.setAttribute("aria-pressed", String(b.dataset.v === snap.prefs[key]));
    }
  }
}

async function command(action, done) {
  try {
    await api("/api/command", { action });
    toast(done);
  } catch (e) {
    toast("לא הצליח: " + e.message);
  }
}

$("goBtn").onclick = () => command("start", "יוצא לנקות");
$("stopBtn").onclick = () => command("stop", "עצר");
$("dockBtn").onclick = () => command("dock", "חוזר לעמדה");

for (const [group, key] of [["modes", "mode"], ["fan", "fan"], ["water", "water"]]) {
  $(group).addEventListener("click", async (e) => {
    const b = e.target.closest("button");
    if (!b) return;
    snap.prefs = await api("/api/prefs", { [key]: b.dataset.v });
    render();
  });
}

function connect() {
  const es = new EventSource("/api/events");
  es.onmessage = (e) => { snap = JSON.parse(e.data); render(); };
  es.onerror = () => {
    es.close();
    $("chip").className = "chip off";
    $("chipText").textContent = "השרת לא זמין";
    setTimeout(connect, 4000);
  };
}

/* ---------- history ---------- */

async function loadHistory() {
  const h = await api("/api/history");
  const runs = h.runs;
  const month = new Date(); month.setDate(1); month.setHours(0, 0, 0, 0);
  const inMonth = runs.filter((r) => r.start * 1000 >= month.getTime());
  const sum = (k) => inMonth.reduce((a, r) => a + (r[k] || 0), 0);
  $("totals").innerHTML = [
    [inMonth.length, "ניקויים"], [sum("minutes"), "דקות"], [sum("area"), "מ״ר"],
  ].map(([v, l]) => `<div class="total"><b>${v}</b><span>${l}</span></div>`).join("");

  const days = [];
  for (let i = 6; i >= 0; i--) {
    const d = new Date(); d.setHours(0, 0, 0, 0); d.setDate(d.getDate() - i);
    const next = d.getTime() + 86400000;
    const mins = runs.filter((r) => r.start * 1000 >= d.getTime() && r.start * 1000 < next)
      .reduce((a, r) => a + (r.minutes || 0), 0);
    days.push({ label: DAY[d.getDay()], mins, today: i === 0 });
  }
  const max = Math.max(30, ...days.map((d) => d.mins));
  $("week").innerHTML = days.map((d) =>
    `<div class="day${d.today ? " today" : ""}" title="${d.mins} דקות"><i style="height:${(d.mins / max) * 100}%"></i>${d.label}</div>`,
  ).join("");

  $("runs").innerHTML = runs.length ? runs.map((r) => {
    const end = r.end ? time(r.end) : "עכשיו";
    const bat = r.battery_start != null ? ` · סוללה ${r.battery_start}%→${r.battery_end ?? "?"}%` : "";
    return `<li class="run"><span class="when">${dayLabel(r.start)}, ${time(r.start)}–${end}</span>
      <span class="min">${r.minutes || 0} דק׳</span>
      <span class="meta">${MODE_NAME[r.mode] || "ניקוי"} · ${r.area || 0} מ״ר${bat}</span></li>`;
  }).join("") : `<li class="empty">עוד אין ניקויים. כל ניקוי מעכשיו יישמר כאן.</li>`;

  $("parts").innerHTML = h.consumables.map((c) => {
    const pct = Math.round(c.left * 100);
    const cls = pct < 15 ? "bad" : pct < 35 ? "mid" : "";
    return `<div class="part"><div class="part-top"><b>${PARTS[c.name] || c.name}</b>
      <span>נשארו ${pct}% · ${c.used_hours} מתוך ${c.life_hours} שעות</span></div>
      <div class="bar"><i class="${cls}" style="width:${pct}%"></i></div>
      <button data-part="${c.name}">החלפתי, לאפס</button></div>`;
  }).join("");

  $("log").innerHTML = h.events.length ? h.events.slice(0, 30).map((e) => {
    const name = e.kind === "command" ? EVENTS.command[e.detail] || e.detail : EVENTS[e.kind] || e.kind;
    const detail = e.kind === "error" ? ERRORS[e.detail.split(":")[1]] || "" : "";
    return `<li><b>${name}</b><span>${detail} ${dayLabel(e.ts)} ${time(e.ts)}</span></li>`;
  }).join("") : `<li>עוד לא קרה כלום.</li>`;
}

$("parts").addEventListener("click", async (e) => {
  const b = e.target.closest("button[data-part]");
  if (!b) return;
  await api(`/api/consumables/${b.dataset.part}/reset`, {});
  toast("אופס. הספירה התחילה מחדש");
  loadHistory();
});

/* ---------- tabs ---------- */

for (const tab of document.querySelectorAll("nav button")) {
  tab.onclick = () => {
    for (const t of document.querySelectorAll("nav button")) t.setAttribute("aria-selected", String(t === tab));
    for (const v of document.querySelectorAll(".view")) v.classList.toggle("on", v.id === "v-" + tab.dataset.v);
    if (tab.dataset.v !== "home") loadHistory().catch(() => toast("לא הצלחתי לטעון היסטוריה"));
  };
}

connect();
