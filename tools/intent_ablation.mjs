// 意图识别消融：对比"第三路（向量分支）"开与关。
//
// 用法：
//   node tools/intent_ablation.mjs <on|off> <keyword|paraphrase|both>
//
// 关键设计：paraphrase 集必须避开 _pattern_recognize 的关键词表，否则关键词那一路
// 已经能覆盖，向量那一路就没有发挥空间，消融会得到"零差异"的假结论。
// 下面的 KEYWORDS 就是从 core/intent_recognizer.py 的 _pattern_recognize 抄下来的，
// 脚本会自检并报出撞车的用例。
const B = 'http://localhost:8000';

const KEYWORDS = [
  '投诉', '经理', '转人工', 'supervisor',
  '太差', '糟糕', 'horrible', '等了很久',
  '?', '？', '怎么', '什么', 'status',
  '帮我', '需要', 'please', 'help',
  '你好', '嗨', 'hello', 'hi',
  '退款', '扣款', '发票', 'refund',
  '崩溃', '报错', 'error', 'crash',
  '密码', '邮箱', '账户', 'password',
];

// 原用例集：多数与关键词表重合，关键词那一路已能覆盖
const KEYWORD_SET = [
  ['退款政策是什么？签收后几天内可以退？', 'query'],
  ['账号被冻结了，错误码 A03 该怎么处理？', 'account'],
  ['生产服务器 CPU 持续 90% 以上，怎么排查？', 'technical'],
  ['我要退款，订单号 A12345', 'request'],
  ['我要投诉，你们服务太差了', 'complaint'],
  ['帮我转人工客服', 'escalation'],
  ['你好', 'greeting'],
  ['你们这次处理得很快，谢谢', 'feedback'],
  ['这个月账单为什么多了 200 块', 'billing'],
  ['怎么修改绑定的手机号', 'account'],
  ['系统报错 500，页面打不开', 'technical'],
  ['把刚才那个订单取消掉', 'request'],
  ['我要找你们主管', 'escalation'],
  ['发票怎么开', 'query'],
];

// 改述集：换词不换意，且刻意避开关键词表 —— 这才是"语义"该发挥的地方
const PARAPHRASE_SET = [
  ['营业时间是几点到几点', 'query'],
  ['会员等级有几档', 'query'],
  ['上个月的账单多算了我五十块', 'billing'],
  ['我要开张报销凭证', 'billing'],
  ['系统一刷新就卡住不动', 'technical'],
  ['接口一直超时，服务没反应', 'technical'],
  ['登录用的手机号想换成新的', 'account'],
  ['我的账号被盗了，想先冻结', 'account'],
  ['把这笔订单取消掉', 'request'],
  ['替我把收货地址改成新的', 'request'],
  ['你们的服务让我很失望', 'complaint'],
  ['我对这次处理结果很不满意', 'complaint'],
  ['叫你们负责人来跟我说', 'escalation'],
  ['我要找你们的上级反映', 'escalation'],
  ['早上好呀', 'greeting'],
  ['在吗', 'greeting'],
  ['这次解决得很快，给你点个赞', 'feedback'],
];

const SETS = { keyword: KEYWORD_SET, paraphrase: PARAPHRASE_SET };

async function runSet(arm, setName) {
  const cases = SETS[setName];
  // 自检：改述集必须不撞关键词表
  const collisions = [];
  for (const [msg] of cases) {
    const hit = KEYWORDS.filter(k => msg.toLowerCase().includes(k));
    if (hit.length) collisions.push(`"${msg}" 撞上 ${hit.join('/')}`);
  }
  const r = await fetch(B + '/eval/run', {
    method: 'POST',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify({ intent_cases: cases.map(([message, expected_intent]) => ({ message, expected_intent })) }),
  });
  const j = await r.json();
  const x = (j.results || []).find(v => v.test_id === 'intent_recognition') || {};
  const m = x.metadata || {};
  console.log(`[分支=${arm} | 用例=${setName}] accuracy=${x.scores ? x.scores.accuracy : '?'}  macro_f1=${x.scores ? x.scores.macro_f1 : '?'}  ${m.correct}/${m.total}`);
  if (collisions.length) console.log('     ⚠ 关键词表撞车（会污染结论）：' + collisions.join(' ; '));
  for (const c of m.cases || []) {
    if (c.expected !== c.predicted) console.log(`     ✗ "${c.message.slice(0, 24)}" 期望=${c.expected} 实际=${c.predicted}`);
  }
  return { accuracy: x.scores ? x.scores.accuracy : null, f1: x.scores ? x.scores.macro_f1 : null };
}

const arm = process.argv[2] || '?';
const which = process.argv[3] || 'both';
for (const s of which === 'both' ? ['keyword', 'paraphrase'] : [which]) await runSet(arm, s);
