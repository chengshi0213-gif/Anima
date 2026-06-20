// 生成紫微交叉验证 golden 快照 —— oracle = 真 iztro（社区标准库 JS 本体）。
// Anima 运行时用 iztro-py（纯 Python 移植），此 golden 用 iztro-JS，二者【不同实现】，
// 故 tests/test_ziwei_crossval.py 是真差分测试：既验适配层映射，又验 iztro-py 与 iztro-JS 移植一致性。
//
// 重生 golden（需 Node + 一次性装 iztro）：
//   cd backend/tests/tools
//   npm init -y && npm install iztro
//   node generate_ziwei_golden.js 60 ../ziwei_golden.json
//
// 注意：时辰索引公式 floor((hour+1)/2) 必须与 divination/ziwei_engine.py 的 _time_index 完全一致。
const { astro } = require("iztro");
const fs = require("fs");

const N = +(process.argv[2] || 60);
const OUT = process.argv[3] || require("path").join(__dirname, "..", "ziwei_golden.json");

// 确定性 LCG（固定 seed，命例稳定可复现）
let _seed = 20260618;
function rnd() {
  _seed = (_seed * 1103515245 + 12345) & 0x7fffffff;
  return _seed / 0x7fffffff;
}
function randint(lo, hi) { return lo + Math.floor(rnd() * (hi - lo + 1)); }

function genBirth() {
  return {
    year: randint(1940, 2015), month: randint(1, 12), day: randint(1, 28),
    hour: randint(0, 22), minute: 30, gender: rnd() < 0.5 ? "male" : "female",
  };
}

const timeIndex = (h) => Math.min(12, Math.floor((h + 1) / 2));

function extract(a) {
  const byBranch = {};
  let ziweiBranch = null, tianfuBranch = null, mingBranch = null, mingGanzhi = null;
  for (const p of a.palaces) {
    const main = (p.majorStars || []).map(s => s.name).sort();
    byBranch[p.earthlyBranch] = {
      tiangan: p.heavenlyStem, main,
      startAge: p.decadal && p.decadal.range ? p.decadal.range[0] : null,
    };
    if (main.includes("紫微")) ziweiBranch = p.earthlyBranch;
    if (main.includes("天府")) tianfuBranch = p.earthlyBranch;
    if (p.name === "命宫") { mingBranch = p.earthlyBranch; mingGanzhi = p.heavenlyStem + p.earthlyBranch; }
  }
  return {
    wuXingJu: a.fiveElementsClass, mingBranch, mingGanzhi,
    shenBranch: a.earthlyBranchOfBodyPalace, ziweiBranch, tianfuBranch, byBranch,
  };
}

const cases = [];
let errors = 0, skipped = 0, attempts = 0;
while (cases.length < N && attempts < N * 10) {
  attempts++;
  const b = genBirth();
  try {
    const a = astro.bySolar(`${b.year}-${b.month}-${b.day}`, timeIndex(b.hour),
      b.gender === "male" ? "男" : "女", true, "zh-CN");
    const ref = extract(a);
    if (!ref.wuXingJu || !ref.ziweiBranch) { skipped++; continue; }
    cases.push({ birth: b, ref });
  } catch (e) { errors++; console.error(`attempt ${attempts} ${JSON.stringify(b)} -> ${e.message}`); }
}

fs.writeFileSync(OUT, JSON.stringify({
  meta: {
    oracle: "iztro (JS 社区标准库) " + require("iztro/package.json").version,
    seed: 20260618, n: cases.length, generatedAt: new Date().toISOString(),
    note: "紫微差分基准。Anima 运行时用 iztro-py(纯Python移植)，此 golden 用 iztro-JS，互为独立实现。核心字段：五行局/命宫干支/身宫/紫微天府位/宫干/主星/大限起运。时辰索引=floor((hour+1)/2)。",
  }, cases,
}, null, 2), "utf-8");

const juCount = {}, mingCount = {};
for (const c of cases) {
  juCount[c.ref.wuXingJu] = (juCount[c.ref.wuXingJu] || 0) + 1;
  mingCount[c.ref.mingBranch] = (mingCount[c.ref.mingBranch] || 0) + 1;
}
console.log(`wrote ${cases.length} cases (${errors} errors, ${skipped} skipped) -> ${OUT}`);
console.log("五行局覆盖:", JSON.stringify(juCount));
console.log("命宫地支覆盖:", JSON.stringify(mingCount));
