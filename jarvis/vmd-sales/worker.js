// JARVIS VMD Sales / Cloudflare Worker
// Monitoring only from verified RSS sources. No unsolicited email without verified
// buyer contact, channel permission, matching model and Gmail OAuth credentials.
const PRICES = Object.freeze({
  "F-MOP LI-ION":144800, "F60 C52":150900,
  "F60 B52 GEL":248400, "F60 B52 LI-ION":268650,
  "F60 BT52 GEL":298800, "F60 BT52 LI-ION":318800,
  "F80 BT58 GEL":439600, "F80 BT58 LI-ION":478800,
  "F80 BT70 GEL":549800, "F80 BT70 LI-ION":645800,
  "F130 BT80 GEL":798800, "F130 BT80 LI-ION":877800,
  "F200 BT90 LI-ION":1468800
});
const SEARCHES = [
  ["ЕИС — поломоечная машина", "поломоечная машина"],
  ["ЕИС — поломоечные машины", "поломоечные машины"]
];
const FEEDS = SEARCHES.map(([name, q]) => ({
  name, url:"https://zakupki.gov.ru/epz/order/extendedsearch/rss.html?searchString="+encodeURIComponent(q)+"&morphology=on&pageNumber=1"
}));
const iso = () => new Date().toISOString();
const json = (data, status=200) => new Response(JSON.stringify(data), {
  status, headers:{"content-type":"application/json; charset=utf-8","cache-control":"no-store"}
});
const decode = s => String(s||"").replace(/<!\[CDATA\[([\s\S]*?)\]\]>/g,"$1")
  .replace(/&quot;/g,'"').replace(/&apos;/g,"'").replace(/&lt;/g,"<")
  .replace(/&gt;/g,">").replace(/&amp;/g,"&")
  .replace(/&#(\d+);/g, (_,n)=>String.fromCodePoint(Number(n)))
  .replace(/<[^>]+>/g," ").replace(/\s+/g," ").trim();
function tag(s, name) {
  const m = String(s).match(new RegExp("<(?:[\\w-]+:)?"+name+"(?:\\s[^>]*)?>([\\s\\S]*?)<\\/(?:[\\w-]+:)?"+name+">","i"));
  return decode(m ? m[1] : "");
}
function findItems(xml) {
  const blocks = Array.from(xml.matchAll(/<item(?:\s[^>]*)?>([\s\S]*?)<\/item>/gi),m=>m[1]).slice(0,75);
  return blocks.map(s=>({
    title:tag(s,"title"), description:tag(s,"description"),
    link:tag(s,"link") || tag(s,"guid"), published:tag(s,"pubDate") || tag(s,"published")
  }));
}
function relevant(title, desc) {
  const text=String(title+" "+desc);
  const isEquipment=/поломоечн|поломойн|поломойк|машин[аы]?.{0,25}(мытья|мойки)\s+пола/i.test(text);
  const isOtherPurpose=/запасн|ремонт|технич.{0,15}обслужив|оказание услуг|аренд|реализац|утилизац|бывш.{0,8}употребл/i.test(String(title));
  return isEquipment && !isOtherPurpose;
}
async function record(env, kind, leadId, detail) {
  await env.DB.prepare("INSERT INTO events(created_at,kind,lead_id,details) VALUES(?,?,?,?)")
    .bind(iso(),kind,leadId||null,String(detail||"").slice(0,800)).run();
}
async function scanFeed(env, feed) {
  let count=0, fresh=0;
  const checked=iso();
  try {
    const res=await fetch(feed.url,{headers:{"accept":"application/rss+xml, application/xml, text/xml","user-agent":"JARVIS-VMD/1.0 monitoring public procurement RSS"},signal:AbortSignal.timeout(18000)});
    if(!res.ok) throw Error("HTTP "+res.status);
    const xml=await res.text();
    if(!/<(?:rss|rdf:RDF|feed)\b/i.test(xml)) throw Error("Источник вернул не RSS/XML");
    for(const item of findItems(xml)) {
      if(!item.title || !relevant(item.title,item.description)) continue;
      let address;try {address=new URL(item.link)}catch {continue}
      if(!["https:","http:"].includes(address.protocol)) continue;
      const url=address.href.split("#")[0];
      const id="vmd-"+Array.from(new Uint8Array(await crypto.subtle.digest("SHA-256",new TextEncoder().encode(url)))).slice(0,12).map(x=>x.toString(16).padStart(2,"0")).join("");
      count++;
      const done=await env.DB.prepare(
        "INSERT OR IGNORE INTO leads(id,source_name,source_url,title,summary,published_at,created_at,last_seen_at,status) VALUES(?,?,?,?,?,?,?,?,?)"
      ).bind(id,feed.name,url,item.title,item.description.slice(0,2000),item.published||null,checked,checked,"DEMAND_FOUND").run();
      if(done.meta?.changes) { fresh++;await record(env,"LEAD_FOUND",id,item.title.slice(0,180)); }
      else await env.DB.prepare("UPDATE leads SET last_seen_at=? WHERE id=?").bind(checked,id).run();
    }
    await env.DB.prepare(
      "INSERT INTO feeds(name,url,last_checked_at,last_success_at,last_error,last_items) VALUES(?,?,?,?,NULL,?) "+
      "ON CONFLICT(name) DO UPDATE SET url=excluded.url,last_checked_at=excluded.last_checked_at,last_success_at=excluded.last_success_at,last_error=NULL,last_items=excluded.last_items"
    ).bind(feed.name,feed.url,checked,iso(),count).run();
    return {name:feed.name,matched:count,new:fresh,ok:true};
  } catch(e) {
    const err=String(e?.message||e).slice(0,250);
    const old=await env.DB.prepare("SELECT last_error FROM feeds WHERE name=?").bind(feed.name).first();
    await env.DB.prepare(
      "INSERT INTO feeds(name,url,last_checked_at,last_error) VALUES(?,?,?,?) "+
      "ON CONFLICT(name) DO UPDATE SET last_checked_at=excluded.last_checked_at,last_error=excluded.last_error"
    ).bind(feed.name,feed.url,checked,err).run();
    if(old?.last_error!==err) await record(env,"FEED_ERROR",null,feed.name+": "+err);
    return {name:feed.name,ok:false,error:err};
  }
}
async function googleToken(env) {
  if(!env.GMAIL_CLIENT_ID||!env.GMAIL_CLIENT_SECRET||!env.GMAIL_REFRESH_TOKEN) return null;
  const resp=await fetch("https://oauth2.googleapis.com/token",{
    method:"POST",headers:{"content-type":"application/x-www-form-urlencoded"},
    body:new URLSearchParams({client_id:env.GMAIL_CLIENT_ID,client_secret:env.GMAIL_CLIENT_SECRET,
      refresh_token:env.GMAIL_REFRESH_TOKEN,grant_type:"refresh_token"})
  });
  if(!resp.ok) throw Error("Gmail OAuth HTTP "+resp.status);
  const body=await resp.json();
  if(!body.access_token) throw Error("No Gmail access token");
  return body.access_token;
}
function proposal(row) {
  const key=row.model_code;
  const price=PRICES[key];
  if(!price) throw Error("Model not approved");
  const first="Здравствуйте!";
  return first+"\r\n\r\n"+
    "Обращаемся по опубликованной потребности: "+row.title+".\r\n"+
    "Предлагаем рассмотреть поломоечную машину VMD "+key+".\r\n"+
    "Ориентировочная розничная цена с НДС по нашему прайсу: "+
    new Intl.NumberFormat("ru-RU").format(price)+" руб.\r\n"+
    "Наличие, точное соответствие техническому заданию, комплектацию, актуальную цену, "+
    "доставку и срок поставки подтвердим по объекту до оформления заказа.\r\n"+
    "При необходимости подготовим подробное предложение после получения ТЗ и требований к месту эксплуатации.\r\n\r\n"+
    "С уважением,\r\nОтдел продаж VMD\r\nvmdirk.ru\r\n";
}
function encodeMime(text) {
  const bytes=new TextEncoder().encode(text);let binary="";
  for(let i=0;i<bytes.length;i++) binary+=String.fromCharCode(bytes[i]);
  return btoa(binary).replace(/\+/g,"-").replace(/\//g,"_").replace(/=+$/,"");
}
async function sendAuthorized(env, token) {
  if(!token) return {sent:0,blocked:"GMAIL_NOT_CONNECTED"};
  let sent=0;
  // Respect the owner's authorisation for targeted procurement responses; never bulk-mail.
  const quota=await env.DB.prepare("SELECT count(*) AS n FROM leads WHERE sent_at>=date('now')").first();
  const remaining=Math.max(0,12-Number(quota?.n||0));
  if(!remaining) return {sent:0,blocked:"DAILY_OUTREACH_CAP"};
  const rows=(await env.DB.prepare(
    "SELECT * FROM leads WHERE status='READY_TO_SEND' AND contact_verified=1 AND outreach_allowed=1 AND model_code IS NOT NULL AND buyer_email IS NOT NULL ORDER BY created_at LIMIT ?"
  ).bind(Math.min(2,remaining)).all()).results||[];
  for(const row of rows) {
    if(!PRICES[row.model_code]||!row.contact_proof_url) continue;
    const locked=await env.DB.prepare(
      "UPDATE leads SET status='SENDING' WHERE id=? AND status='READY_TO_SEND'"
    ).bind(row.id).run();
    if(!locked.meta?.changes) continue;
    try {
      const subject="Предложение VMD — "+row.title.slice(0,100);
      const mime="To: "+row.buyer_email+"\r\nSubject: =?UTF-8?B?"+btoa(String.fromCharCode(...new TextEncoder().encode(subject)))+"?=\r\n"+
        "MIME-Version: 1.0\r\nContent-Type: text/plain; charset=UTF-8\r\n\r\n"+proposal(row);
      const resp=await fetch("https://gmail.googleapis.com/gmail/v1/users/me/messages/send",{
        method:"POST",headers:{"Authorization":"Bearer "+token,"content-type":"application/json"},
        body:JSON.stringify({raw:encodeMime(mime)})
      });
      if(!resp.ok) throw Error("Gmail send HTTP "+resp.status);
      const sentMessage=await resp.json();
      await env.DB.prepare(
        "UPDATE leads SET status='QUOTE_SENT', sent_at=?, gmail_id=?, gmail_thread_id=?, error=NULL WHERE id=?"
      ).bind(iso(),sentMessage.id||null,sentMessage.threadId||null,row.id).run();
      await record(env,"QUOTE_SENT",row.id,"Gmail message "+(sentMessage.id||""));
      sent++;
    } catch(e) {
      // A send can have succeeded before an error; never retry automatically.
      await env.DB.prepare("UPDATE leads SET status='SEND_REVIEW',error=? WHERE id=?")
        .bind(String(e?.message||e).slice(0,250),row.id).run();
      await record(env,"SEND_REVIEW",row.id,String(e?.message||e));
    }
  }
  return {sent};
}
async function checkReplies(env, token) {
  if(!token) return {replies:0};
  const tracking=(await env.DB.prepare(
    "SELECT id,gmail_thread_id,sent_at FROM leads WHERE status='QUOTE_SENT' AND gmail_thread_id IS NOT NULL LIMIT 80"
  ).all()).results||[];
  if(!tracking.length) return {replies:0};
  const ids=new Map(tracking.map(r=>[r.gmail_thread_id,r]));
  const q=encodeURIComponent("in:inbox newer_than:30d");
  const res=await fetch("https://gmail.googleapis.com/gmail/v1/users/me/messages?q="+q+"&maxResults=40",{
    headers:{"Authorization":"Bearer "+token}});
  if(!res.ok) throw Error("Gmail inbox HTTP "+res.status);
  const data=await res.json();
  let replies=0;
  for(const m of data.messages||[]) {
    const row=ids.get(m.threadId);if(!row) continue;
    const item=await fetch("https://gmail.googleapis.com/gmail/v1/users/me/messages/"+encodeURIComponent(m.id)+"?format=metadata",{
      headers:{"Authorization":"Bearer "+token}});
    if(!item.ok) continue;
    const mail=await item.json();
    if(Number(mail.internalDate||0)<=Date.parse(row.sent_at||"1970-01-01")) continue;
    await env.DB.prepare("UPDATE leads SET status='REPLIED',reply_at=?,reply_snippet=? WHERE id=? AND status='QUOTE_SENT'")
      .bind(iso(),String(mail.snippet||"").slice(0,500),row.id).run();
    await record(env,"REPLY_RECEIVED",row.id,"Reply recorded; human negotiation required");
    replies++;
  }
  return {replies};
}

// Public keyless GenTender API, documented at https://gentender.ru/api
// Their catalog refreshes daily, so do not poll faster than once per hour.
// The source includes current open procedures by default, not direct permission to email.
const GT_SOURCES=[
 {name:"GenTender — поломоечная",q:"поломоечная"},
 {name:"GenTender — поломоечные",q:"поломоечные"}
];
async function scanGentender(env,feed) {
 const url="https://gentender.ru/api/tenders/search?q="+encodeURIComponent(feed.q)+"&limit=50";
 const checked=iso();
 const old=await env.DB.prepare("SELECT last_checked_at FROM feeds WHERE name=?").bind(feed.name).first();
 if(old?.last_checked_at && Date.now()-Date.parse(old.last_checked_at)<60*60*1000) {
   return {name:feed.name,skipped:true,reason:"hourly API throttle"};
 }
 let fresh=0,matched=0;
 try {
   const response=await fetch(url,{headers:{"accept":"application/json","user-agent":"JARVIS-VMD/1.1 business-procurement-monitor"},signal:AbortSignal.timeout(14000)});
   if(!response.ok) throw Error("GenTender HTTP "+response.status);
   const data=await response.json();
   if(!Array.isArray(data.rows)) throw Error("GenTender changed API response: rows missing");
   for(const item of data.rows.slice(0,50)) {
     const title=String(item.title||"").trim();
     if(!title || !relevant(title,"")) continue;
     const reg=String(item.reg_number||"").trim();
     if(!reg) continue;
     // Canonical link remains a source search, not an unverified tender detail URL.
     const sourceUrl="https://gentender.ru/search?q="+encodeURIComponent(reg);
     const id="GT-"+reg.replace(/[^a-z0-9_-]/gi,"").slice(0,64);
     if(id.length<5) continue;
     matched++;
     const meta=[
       "Заказчик: "+String(item.customer_name||"не указан"),
       "Регион: "+String(item.region||"не указан"),
       "Цена закупки: "+(Number(item.price)>0?String(item.price)+" ₽":"нет"),
       "Срок подачи: "+String(item.deadline_date||"не указан"),
       "Статус: "+String(item.status_label||"не указан"),
       "Закон: "+String(item.law||"не указан"),
       "Площадка: "+String(item.etp_name||"не указана"),
       "Номер: "+reg,
       "Не подтверждает соответствие VMD или возможность отправить КП напрямую"
     ].join(" | ").slice(0,1900);
     const inserted=await env.DB.prepare(
       "INSERT OR IGNORE INTO leads(id,source_name,source_url,title,summary,published_at,created_at,last_seen_at,status) VALUES(?,?,?,?,?,?,?,?,?)"
     ).bind(id,feed.name,sourceUrl,title,meta,null,checked,checked,"DEMAND_FOUND").run();
     if(inserted.meta?.changes){fresh++;await record(env,"LEAD_FOUND",id,title.slice(0,180));}
     else await env.DB.prepare("UPDATE leads SET last_seen_at=? WHERE id=?").bind(checked,id).run();
   }
   await env.DB.prepare(
     "INSERT INTO feeds(name,url,last_checked_at,last_success_at,last_error,last_items) VALUES(?,?,?,?,NULL,?) "+
     "ON CONFLICT(name) DO UPDATE SET url=excluded.url,last_checked_at=excluded.last_checked_at,last_success_at=excluded.last_success_at,last_error=NULL,last_items=excluded.last_items"
   ).bind(feed.name,url,checked,iso(),matched).run();
   return {name:feed.name,ok:true,matched,new:fresh};
 } catch(e) {
   const err=String(e?.message||e).slice(0,250);
   await env.DB.prepare(
     "INSERT INTO feeds(name,url,last_checked_at,last_error) VALUES(?,?,?,?) "+
     "ON CONFLICT(name) DO UPDATE SET last_checked_at=excluded.last_checked_at,last_error=excluded.last_error"
   ).bind(feed.name,url,checked,err).run();
   await record(env,"FEED_ERROR",null,feed.name+": "+err);
   return {name:feed.name,ok:false,error:err};
 }
}

async function run(env) {
  const results=[];
  for(const feed of GT_SOURCES) results.push(await scanGentender(env,feed));
  let email={sent:0,blocked:"GMAIL_NOT_CONNECTED"}, inbox={replies:0};
  try {
    const token=await googleToken(env);
    email=await sendAuthorized(env,token);
    inbox=await checkReplies(env,token);
  } catch(e) {await record(env,"MAIL_ERROR",null,String(e?.message||e));}
  return {time:iso(),feeds:results,email,inbox};
}
const authorized=(r,env)=>Boolean(env.ADMIN_TOKEN && r.headers.get("authorization")==="Bearer "+env.ADMIN_TOKEN);
export default {
  async scheduled(event, env, ctx) { ctx.waitUntil(run(env)); },
  async fetch(request,env,ctx) {
    const u=new URL(request.url);
    if(u.pathname==="/health") {
      const stats=await env.DB.prepare(
        "SELECT (SELECT count(*) FROM leads) total_leads, "+
        "(SELECT count(*) FROM leads WHERE status='DEMAND_FOUND') to_review, "+
        "(SELECT count(*) FROM leads WHERE status='QUOTE_SENT') sent_quotes, "+
        "(SELECT max(last_success_at) FROM feeds WHERE name LIKE 'GenTender%') last_success"
      ).first();
      return json({
        service:"JARVIS VMD Sales",status:"running",monitoring:"every 5 minutes",
        source:"GenTender public procurement API",last_success:stats?.last_success||null,
        total_records:Number(stats?.total_leads||0),to_review:Number(stats?.to_review||0),
        quotes_sent:Number(stats?.sent_quotes||0),
        gmailConnected:Boolean(env.GMAIL_CLIENT_ID && env.GMAIL_CLIENT_SECRET && env.GMAIL_REFRESH_TOKEN)
      });
    }
    if(!authorized(request,env)) return json({error:"Unauthorized"},401);
    if(u.pathname==="/admin/run" && request.method==="POST") return json(await run(env));
    if(u.pathname==="/admin/status" && request.method==="GET") {
      const leads=await env.DB.prepare("SELECT status,COUNT(*) AS total FROM leads GROUP BY status").all();
      const feeds=await env.DB.prepare("SELECT * FROM feeds ORDER BY name").all();
      const recent=await env.DB.prepare("SELECT created_at,kind,lead_id,details FROM events ORDER BY id DESC LIMIT 25").all();
      return json({time:iso(),leads:leads.results,feeds:feeds.results,events:recent.results});
    }
    if(u.pathname==="/admin/leads" && request.method==="GET") {
      const rows=await env.DB.prepare("SELECT * FROM leads ORDER BY created_at DESC LIMIT 100").all();
      return json({leads:rows.results});
    }
    if(u.pathname==="/admin/qualify" && request.method==="POST") {
      let body;try{body=await request.json()}catch{return json({error:"Invalid JSON"},400)}
      const email=String(body.buyer_email||"").trim();
      if(!body.id || !PRICES[body.model_code] || !/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email) ||
        !body.contact_proof_url?.startsWith("https://") || body.outreach_allowed!==true ||
        body.contact_verified!==true) return json({error:"Needs existing ID, approved model, verified procurement contact source and allowed direct outreach"},400);
      const updated=await env.DB.prepare(
        "UPDATE leads SET model_code=?,buyer_name=?,buyer_email=?,contact_proof_url=?,contact_verified=1,outreach_allowed=1,status='READY_TO_SEND' "+
        "WHERE id=? AND status IN ('DEMAND_FOUND','QUALIFIED')"
      ).bind(body.model_code,String(body.buyer_name||"").slice(0,200),email,
        body.contact_proof_url,body.id).run();
      if(!updated.meta?.changes) return json({error:"Lead not found or already processed"},409);
      await record(env,"READY_TO_SEND",body.id,"Verified contact and matching model approved");
      return json({ok:true,status:"READY_TO_SEND"});
    }
    return json({error:"Not found"},404);
  }
};
