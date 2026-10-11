const B='http://localhost:8000';
const DOCS=[
 {title:'退款政策',content:'订单签收后 7 天内可无条件申请退款，15 天内可申请换货。退款需在 App 订单详情页提交，客服无权直接操作退款。退款到账通常 3-5 个工作日。超过 15 天需走售后工单流程。'},
 {title:'发票开具流程',content:'增值税普通发票与专用发票均可开具。需提供公司名称、纳税人识别号、开户行及账号。电子发票可在订单详情页下载，纸质发票 7 个工作日内寄出。'},
 {title:'会员等级与积分规则',content:'会员分青铜、白银、黄金三级，按年消费额升级。每消费 1 元得 1 积分，积分可在积分商城兑换优惠券与实物。等级有效期至次年年底。'},
 {title:'服务器CPU告警处理手册',content:'生产服务器 CPU 持续超过 90% 时：先用 top 确认整体负载与 load average；再用 top -H -p PID 定位高占用线程；检查是否有定时批处理在运行；查看最近发布记录；必要时摘除流量后重启。'},
 {title:'数据库连接超时排查',content:'应用报数据库连接超时，依次检查：连接池最大连接数是否被打满、是否存在连接泄漏、慢查询是否长期占用连接、网络与防火墙策略。常见根因是慢查询拖垮连接池。'},
 {title:'缓存击穿与雪崩应对',content:'热点 key 失效瞬间大量请求打到数据库称为缓存击穿，用互斥锁或逻辑过期解决；大量 key 同时过期称为雪崩，用随机 TTL 与多级缓存缓解。'},
 {title:'账号冻结处理流程',content:'账号冻结原因代码：A01 异常登录，A02 支付风险，A03 违规内容。A01 与 A02 可引导用户自助解冻，A03 必须转人工审核。需用户提供注册手机号与最近登录时间。'},
 {title:'密码重置方式',content:'支持手机验证码重置、邮箱链接重置两种方式。重置链接有效期 30 分钟。连续 5 次验证失败将锁定 1 小时。'},
 {title:'双因素认证开启步骤',content:'在安全设置中开启双因素认证，使用 TOTP 应用扫码绑定，并保存 10 个备用码。备用码仅可使用一次。'},
 {title:'配送时效说明',content:'同城订单次日达，省内 2-3 天，偏远地区 5-7 天。法定节假日整体顺延 1-2 天。大促期间可能延迟。'},
 {title:'售后维修申请',content:'保修期内可申请寄修或上门维修。寄修需在系统提交申请并填写故障描述，维修进度可在售后页查询。人为损坏不在保修范围。'},
 {title:'数据导出与隐私政策',content:'用户可申请导出个人数据副本，或申请删除账号及个人信息。提交后 15 个工作日内处理完成。删除后不可恢复。'}
];
const EXACT=[
 ['退款政策是什么？签收后几天内可以退？','退款政策'],
 ['发票怎么开？需要提供什么资料？','发票开具流程'],
 ['会员积分怎么兑换？等级怎么升？','会员等级与积分规则'],
 ['CPU 告警处理手册里第一步是什么？','服务器CPU告警处理手册'],
 ['密码怎么重置？','密码重置方式'],
 ['配送时效是多久？偏远地区呢？','配送时效说明'],
];
const PARA=[
 ['买错了不想要了，钱还能拿回来吗','退款政策'],
 ['我想报销需要凭证，那个东西在哪里下载','发票开具流程'],
 ['攒的那些分能换东西吗','会员等级与积分规则'],
 ['程序连不上数据库了，一直报超时','数据库连接超时排查'],
 ['同一批请求打过来系统就扛不住','缓存击穿与雪崩应对'],
 ['系统说我账号有问题，用不了了','账号冻结处理流程'],
 ['收到的包裹太慢了，什么时候能到','配送时效说明'],
 ['东西坏了想送去修怎么弄','售后维修申请'],
];
const INTENTS=[
 ['退款政策是什么？签收后几天内可以退？','query'],
 ['账号被冻结了，错误码 A03 该怎么处理？','account'],
 ['生产服务器 CPU 持续 90% 以上，怎么排查？','technical'],
 ['我要退款，订单号 A12345','request'],
 ['我要投诉，你们服务太差了','complaint'],
 ['帮我转人工客服','escalation'],
 ['你好','greeting'],
 ['你们这次处理得很快，谢谢','feedback'],
 ['这个月账单为什么多了 200 块','billing'],
 ['怎么修改绑定的手机号','account'],
 ['系统报错 500，页面打不开','technical'],
 ['把刚才那个订单取消掉','request'],
 ['我要找你们主管','escalation'],
 ['发票怎么开','query'],
];
const post=async(p,b)=>{const r=await fetch(B+p,{method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify(b)});return {code:r.status,json:await r.json().catch(()=>null)}};
await post('/knowledge/add',{documents:DOCS});
const st=await (await fetch(B+'/knowledge/stats')).json();
console.log('知识库片段数: '+st.total_chunks+'   （文档 '+DOCS.length+' 篇）');
async function runSet(name,cases){
  let t1=0,t3=0;const rows=[];
  for(const [q,exp] of cases){
    const r=await fetch(B+'/search?query='+encodeURIComponent(q)+'&top_k=3',{method:'POST'});
    const j=await r.json();
    const titles=(j.results||j.items||j||[]).map(x=>x.title||'');
    const ok1=titles[0]===exp, ok3=titles.slice(0,3).includes(exp);
    if(ok1)t1++; if(ok3)t3++;
    rows.push('   '+(ok1?'✓':(ok3?'~':'✗'))+' 期望='+exp+' 实际top3=['+titles.slice(0,3).join(' | ')+']');
  }
  console.log('\n['+name+']  top1='+(t1/cases.length*100).toFixed(1)+'%  top3='+(t3/cases.length*100).toFixed(1)+'%  (n='+cases.length+')');
  rows.forEach(r=>console.log(r));
}
await runSet('关键词类',EXACT);
await runSet('改述类',PARA);
const ev=await post('/eval/run',{intent_cases:INTENTS.map(([message,expected_intent])=>({message,expected_intent}))});
const e=ev.json;
console.log('\n[意图识别] accuracy='+(e.avg_scores&&e.avg_scores.intent_accuracy)+'  pass_rate='+e.pass_rate);
for(const x of e.results||[]){if(x.test_id!=='intent_recognition')continue;
  console.log('   '+(x.metadata?x.metadata.correct:'?')+'/'+(x.metadata?x.metadata.total:'?')+' 正确, macro_f1='+x.scores.macro_f1);
  for(const c of (x.metadata&&x.metadata.cases)||[]) if(c.expected!==c.predicted) console.log('     ✗ "'+c.message.slice(0,18)+'" 期望='+c.expected+' 实际='+c.predicted);
}
