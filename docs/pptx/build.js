/**
 * Phase 1.1 系统宣发与说明 PPT — PptxGenJS 生成
 * 配色：Teal Trust（028090, 00A896, 02C39A），深色封面/总结
 * 内容基于 Phase1.1开发交付包.md，面向宣发与产品说明
 */

const pptxgen = require('pptxgenjs');
const path = require('path');

const COLORS = {
  teal: '028090',
  seafoam: '00A896',
  mint: '02C39A',
  dark: '212121',
  light: 'F2F2F2',
  white: 'FFFFFF',
  gray: '64748B',
};

function addTitleSlide(pres) {
  const slide = pres.addSlide();
  slide.background = { color: COLORS.teal };
  slide.addShape(pres.shapes.RECTANGLE, {
    x: 0, y: 0, w: 10, h: 0.2,
    fill: { color: COLORS.seafoam },
    line: { type: 'none' },
  });
  slide.addText('Phase 1.1 交易系统', {
    x: 0.5, y: 1.8, w: 9, h: 1.2,
    fontSize: 44, fontFace: 'Arial', color: COLORS.white, bold: true, align: 'center',
  });
  slide.addText('宣发与产品说明', {
    x: 0.5, y: 3.0, w: 9, h: 0.7,
    fontSize: 28, fontFace: 'Arial', color: COLORS.light, align: 'center',
  });
  slide.addText('基于 Phase1.0 + Phase1.1 技术设计', {
    x: 0.5, y: 4.2, w: 9, h: 0.5,
    fontSize: 14, fontFace: 'Arial', color: COLORS.mint, align: 'center',
  });
}

function addTocSlide(pres) {
  const slide = pres.addSlide();
  slide.background = { color: COLORS.light };
  slide.addShape(pres.shapes.RECTANGLE, {
    x: 0, y: 0, w: 0.15, h: 5.625,
    fill: { color: COLORS.teal },
    line: { type: 'none' },
  });
  slide.addText('目录', {
    x: 0.6, y: 0.4, w: 8, h: 0.7,
    fontSize: 32, fontFace: 'Arial', color: COLORS.teal, bold: true,
  });
  const items = [
    '系统简介 — 目标与定位',
    '核心能力 — 对账与互斥锁',
    '核心能力 — 外部同步与定价',
    '核心能力 — 风控与挂起/恢复',
    '阶段规划与执行顺序',
    '总结与下一步',
  ];
  slide.addText(
    items.map((t, i) => ({ text: t, options: { bullet: true, breakLine: true } })).concat([{ text: '', options: {} }]),
    {
      x: 0.8, y: 1.4, w: 8.5, h: 3.5,
      fontSize: 18, fontFace: 'Arial', color: COLORS.dark,
      paraSpaceAfter: 6,
    }
  );
}

function addIntroSlide(pres) {
  const slide = pres.addSlide();
  slide.background = { color: COLORS.white };
  slide.addShape(pres.shapes.RECTANGLE, {
    x: 0, y: 0, w: 10, h: 1.1,
    fill: { color: COLORS.teal },
    line: { type: 'none' },
  });
  slide.addText('系统简介', {
    x: 0.5, y: 0.35, w: 9, h: 0.6,
    fontSize: 28, fontFace: 'Arial', color: COLORS.white, bold: true,
  });
  slide.addText('Phase 1.1 在 Phase1.0 基础上，聚焦对账、恢复与风控的闭环能力，确保策略在异常与超仓场景下可安全挂起、可审计恢复。', {
    x: 0.6, y: 1.5, w: 8.8, h: 0.9,
    fontSize: 16, fontFace: 'Arial', color: COLORS.dark,
  });
  slide.addText('核心目标', {
    x: 0.6, y: 2.6, w: 4, h: 0.45,
    fontSize: 18, fontFace: 'Arial', color: COLORS.teal, bold: true,
  });
  const goals = [
    '对账/恢复与下单路径互斥，避免并发写导致状态错乱',
    '外部同步（EXTERNAL_SYNC）成交可落库并参与持仓校正',
    '风控不通过时安全挂起（PAUSED），强校验通过后可恢复',
    '全流程可追溯：终态日志、diff 标准、审计链',
  ];
  slide.addText(
    goals.map((t) => ({ text: t, options: { bullet: true, breakLine: true } })).concat([{ text: '', options: {} }]),
    { x: 0.6, y: 3.0, w: 8.8, h: 2.2, fontSize: 14, fontFace: 'Arial', color: COLORS.dark, paraSpaceAfter: 4 }
  );
}

function addReconcileLockSlide(pres) {
  const slide = pres.addSlide();
  slide.background = { color: COLORS.white };
  slide.addShape(pres.shapes.RECTANGLE, {
    x: 0, y: 0, w: 10, h: 1.1,
    fill: { color: COLORS.seafoam },
    line: { type: 'none' },
  });
  slide.addText('核心能力：对账与互斥锁', {
    x: 0.5, y: 0.35, w: 9, h: 0.6,
    fontSize: 26, fontFace: 'Arial', color: COLORS.white, bold: true,
  });
  slide.addText('ReconcileLock（DB 原子锁 + TTL）', {
    x: 0.6, y: 1.35, w: 5, h: 0.45,
    fontSize: 16, fontFace: 'Arial', color: COLORS.teal, bold: true,
  });
  const lockItems = [
    '基于单条原子 UPDATE 的租约锁，禁止 SELECT FOR UPDATE',
    '默认 TTL 30 秒，超时未续期则锁失效，崩溃后可恢复',
    '对账路径与下单路径共用同一把锁，持锁内仅做 DB 写与状态更新',
    '锁外执行：拉取交易所数据、差异计算、风控计算',
  ];
  slide.addText(
    lockItems.map((t) => ({ text: t, options: { bullet: true, breakLine: true } })).concat([{ text: '', options: {} }]),
    { x: 0.6, y: 1.85, w: 8.8, h: 2.0, fontSize: 14, fontFace: 'Arial', color: COLORS.dark, paraSpaceAfter: 4 }
  );
  slide.addText('互斥保证', {
    x: 0.6, y: 4.0, w: 4, h: 0.4,
    fontSize: 16, fontFace: 'Arial', color: COLORS.teal, bold: true,
  });
  slide.addText('同一时刻仅一条写路径生效：对账写持仓与信号驱动下单不会并发写 position_snapshot / trade，避免数据竞争与重复写入。', {
    x: 0.6, y: 4.4, w: 8.8, h: 0.85,
    fontSize: 13, fontFace: 'Arial', color: COLORS.dark,
  });
}

function addExternalSyncSlide(pres) {
  const slide = pres.addSlide();
  slide.background = { color: COLORS.white };
  slide.addShape(pres.shapes.RECTANGLE, {
    x: 0, y: 0, w: 10, h: 1.1,
    fill: { color: COLORS.mint },
    line: { type: 'none' },
  });
  slide.addText('核心能力：外部同步与定价', {
    x: 0.5, y: 0.35, w: 9, h: 0.6,
    fontSize: 26, fontFace: 'Arial', color: COLORS.dark, bold: true,
  });
  slide.addText('EXTERNAL_SYNC', {
    x: 0.6, y: 1.35, w: 4, h: 0.45,
    fontSize: 16, fontFace: 'Arial', color: COLORS.teal, bold: true,
  });
  const syncItems = [
    '来自交易所/外部系统的成交以 source_type=EXTERNAL_SYNC 落库',
    '幂等键：(strategy_id, external_trade_id)，唯一约束防重',
    '对账结果通过 PositionManager.reconcile 生成 EXTERNAL_SYNC trade 并更新 position_snapshot',
    'position_reconcile_log 记录 event_type（RECONCILE_START/END、SYNC_TRADE、OVER_POSITION、STRATEGY_PAUSED/RESUMED 等）',
  ];
  slide.addText(
    syncItems.map((t) => ({ text: t, options: { bullet: true, breakLine: true } })).concat([{ text: '', options: {} }]),
    { x: 0.6, y: 1.85, w: 8.8, h: 2.1, fontSize: 13, fontFace: 'Arial', color: COLORS.dark, paraSpaceAfter: 4 }
  );
  slide.addText('定价优先级（从高到低）', {
    x: 0.6, y: 4.0, w: 5, h: 0.4,
    fontSize: 14, fontFace: 'Arial', color: COLORS.teal, bold: true,
  });
  slide.addText('交易所成交价 → 本地参考价 → 兜底价；档位可追溯。', {
    x: 0.6, y: 4.4, w: 8.8, h: 0.5,
    fontSize: 13, fontFace: 'Arial', color: COLORS.dark,
  });
}

function addRiskResumeSlide(pres) {
  const slide = pres.addSlide();
  slide.background = { color: COLORS.white };
  slide.addShape(pres.shapes.RECTANGLE, {
    x: 0, y: 0, w: 10, h: 1.1,
    fill: { color: COLORS.teal },
    line: { type: 'none' },
  });
  slide.addText('核心能力：风控与挂起/恢复', {
    x: 0.5, y: 0.35, w: 9, h: 0.6,
    fontSize: 26, fontFace: 'Arial', color: COLORS.white, bold: true,
  });
  const riskItems = [
    '对账/EXTERNAL_SYNC 完成后执行 RiskManager 全量检查',
    '超仓/风控不通过：PAUSED + STRATEGY_PAUSED 终态日志（含差异快照），同一事务',
    '信号入口返回 200 + 业务字段拒绝原因，避免 TradingView 误判重试',
    'POST /strategy/{id}/resume：强校验通过才恢复，失败返回 400 + 标准 diff（code / checks / snapshot）',
    '恢复成功：STRATEGY_RESUMED 终态日志与状态更新同一一致性边界',
  ];
  slide.addText(
    riskItems.map((t) => ({ text: t, options: { bullet: true, breakLine: true } })).concat([{ text: '', options: {} }]),
    { x: 0.6, y: 1.4, w: 8.8, h: 3.8, fontSize: 13, fontFace: 'Arial', color: COLORS.dark, paraSpaceAfter: 4 }
  );
}

function addRoadmapSlide(pres) {
  const slide = pres.addSlide();
  slide.background = { color: COLORS.light };
  slide.addShape(pres.shapes.RECTANGLE, {
    x: 0, y: 0, w: 0.15, h: 5.625,
    fill: { color: COLORS.teal },
    line: { type: 'none' },
  });
  slide.addText('阶段规划与执行顺序', {
    x: 0.6, y: 0.35, w: 8, h: 0.6,
    fontSize: 26, fontFace: 'Arial', color: COLORS.teal, bold: true,
  });
  const rows = [
    [
      { text: '步骤', options: { fill: { color: COLORS.teal }, color: COLORS.white, bold: true } },
      { text: '开发项', options: { fill: { color: COLORS.teal }, color: COLORS.white, bold: true } },
      { text: '说明', options: { fill: { color: COLORS.teal }, color: COLORS.white, bold: true } },
    ],
    ['1', 'A1 / A2 / A3', '数据库迁移（锁、EXTERNAL_SYNC、reconcile_log）'],
    ['2', 'C1', 'ReconcileLock（DB 原子锁 + TTL）'],
    ['3', 'C2', '下单路径互斥保护'],
    ['4', 'C3', 'PositionManager.reconcile → EXTERNAL_SYNC'],
    ['5', 'C4', 'RiskManager post-sync full check'],
    ['6', 'C5 / C6', '超仓挂起 + STRATEGY_PAUSED 终态日志'],
    ['7', 'B1', 'POST /strategy/{id}/resume（强校验 + diff）'],
    ['8', 'C7', 'STRATEGY_RESUMED 终态日志'],
    ['9', 'D1～D6', '测试（锁、定价、挂起事务、Resume、互斥）'],
    ['10', 'B2', 'GET /strategy/{id}/status（可选）'],
  ];
  slide.addTable(rows, {
    x: 0.6, y: 1.1, w: 8.8, h: 4.0,
    colW: [0.6, 2.2, 5.6],
    border: { pt: 0.5, color: 'CCCCCC' },
    fontSize: 11,
    align: 'left',
    valign: 'middle',
    margin: 4,
  });
}

function addSummarySlide(pres) {
  const slide = pres.addSlide();
  slide.background = { color: COLORS.teal };
  slide.addShape(pres.shapes.RECTANGLE, {
    x: 0, y: 5.2, w: 10, h: 0.425,
    fill: { color: COLORS.seafoam },
    line: { type: 'none' },
  });
  slide.addText('总结与下一步', {
    x: 0.5, y: 0.6, w: 9, h: 0.8,
    fontSize: 36, fontFace: 'Arial', color: COLORS.white, bold: true, align: 'center',
  });
  const points = [
    'Phase 1.1 交付对账锁、EXTERNAL_SYNC、风控挂起/恢复与 Resume API 的完整闭环',
    '推荐按文档顺序实施，保证依赖与验收可追溯',
    '后续可进入 Phase 1.2 或更高版本进行能力扩展',
  ];
  slide.addText(
    points.map((t) => ({ text: t, options: { bullet: true, breakLine: true } })).concat([{ text: '', options: {} }]),
    {
      x: 0.8, y: 1.7, w: 8.4, h: 2.2,
      fontSize: 18, fontFace: 'Arial', color: COLORS.light,
      paraSpaceAfter: 8,
    }
  );
  slide.addText('Phase 1.1 开发交付包 v1.0.0 · 基于 Phase1.0 v1.3.1 + Phase1.1 技术设计', {
    x: 0.5, y: 4.5, w: 9, h: 0.5,
    fontSize: 12, fontFace: 'Arial', color: COLORS.mint, align: 'center',
  });
}

async function main() {
  const pres = new pptxgen();
  pres.layout = 'LAYOUT_16x9';
  pres.author = 'Trading System';
  pres.title = 'Phase 1.1 交易系统 — 宣发与说明';

  addTitleSlide(pres);
  addTocSlide(pres);
  addIntroSlide(pres);
  addReconcileLockSlide(pres);
  addExternalSyncSlide(pres);
  addRiskResumeSlide(pres);
  addRoadmapSlide(pres);
  addSummarySlide(pres);

  const outPath = path.join(__dirname, '..', 'Phase1.1系统宣发说明.pptx');
  await pres.writeFile({ fileName: outPath });
  console.log('Generated:', outPath);
}

main().catch((err) => {
  console.error(err);
  process.exit(1);
});
