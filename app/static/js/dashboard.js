'use strict';
const $ = id => document.getElementById(id);
let channelNames = {}, config = null;
const colors = ['#3b82f6','#10b981','#8b5cf6','#f59e0b','#ef4444'];
let current = null, applied = null, page = 1, entity = '', kind = 'all', searchTimer, requestId = 0, tableId = 0, modalId = 0;
const escape = value => String(value ?? '').replace(/[&<>"']/g, s => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[s]));
const num = value => Number(value).toLocaleString('ko-KR');
function localTime(iso) { return iso ? new Intl.DateTimeFormat('sv-SE',{timeZone:'Asia/Seoul',year:'numeric',month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit'}).format(new Date(iso)) : '메시지 없음'; }
function safeLink(url) { try { const u = new URL(url); return u.protocol === 'https:' ? escape(u.href) : '#'; } catch { return '#'; } }
const link = (url, label) => `<a href="${safeLink(url)}" target="_blank" rel="noopener noreferrer">${escape(label)} ↗</a>`;
function readFilters() {
  const channels = [...document.querySelectorAll('[name=channel]:checked')].map(el=>el.value);
  if (!channels.length && config.channels.length) throw new Error('채널을 하나 이상 선택하세요.');
  if (!$('start').value || !$('end').value || $('start').value > $('end').value) throw new Error('시작일과 종료일을 확인하세요.');
  return {start:$('start').value,end:$('end').value,...(channels.length?{channels:channels.join(',')}:{}),mode:$('mode').value,exclude_pins:String($('exclude-pins').checked),exclude_lists:String($('exclude-lists').checked),scope:$('other').checked?'all':'stocks'};
}
const params = (filters, extra={}) => new URLSearchParams({...filters,...extra}).toString();
async function api(path, options) {
  const response = await fetch(path, options);
  if (!response.ok) {
    const body = await response.json().catch(()=>({}));
    throw new Error(typeof body.detail==='string'?body.detail:`데이터 요청에 실패했습니다 (${response.status}).`);
  }
  return response.json();
}
function showError(message) {$('error').hidden=false; $('error').textContent=message;}
function notify(message) { $('toast').textContent=message; $('toast').hidden=false; clearTimeout(notify.timer); notify.timer=setTimeout(()=>$('toast').hidden=true,4500); }
function setTheme(light) {
  document.body.classList.toggle('theme-light', light);
  $('theme').textContent=light?'☾ 다크 모드':'☀ 라이트 모드';
  try {localStorage.setItem('telegram-theme',light?'light':'dark');}catch{}
}
async function loadDashboard() {
  const id=++requestId;
  let filters;
  try {filters=readFilters();} catch(err) {showError(err.message);return;}
  $('error').hidden=true; $('filters').setAttribute('aria-busy','true');
  try {
    const data=await api('/api/dashboard?'+params(filters));
    if(id!==requestId)return;
    if(typeof clearAIBrief==='function')clearAIBrief();
    applied=filters; current=data; page=1; entity='';
    history.replaceState(null,'','/?'+params(filters));
    renderDashboard(data); await loadPosts();
  } catch(err) {if(id===requestId) showError(err.message+' 화면은 마지막으로 성공한 조회 결과를 유지합니다.');}
  finally {if(id===requestId)$('filters').removeAttribute('aria-busy');}
}
function renderDashboard(data) {
  const missing=data.coverage_warnings||[];
  $('coverage-warning').hidden=!missing.length;
  $('coverage-warning').textContent=missing.length?'미수집·경계 미확인 기간이 있습니다. 현재 수치는 확보한 메시지만 포함합니다. 채널 관리에서 해당 기간을 수집하세요. '+missing.map(w=>w.message).join(' '):'';
  const s=data.stats,r=data.ranking,first=r[0], mode=data.filters.mode==='clusters';
  $('stat-posts').textContent=num(s.posts); $('stat-text').textContent=num(s.text_posts); $('stat-entities').textContent=num(s.entities);
  $('stat-mentions').textContent=`종목×게시물 ${num(s.entity_mentions)}건`;
  $('stat-top').textContent=first?.entity||'언급 없음';
  $('stat-top-sub').textContent=first?`${num(first.count)}${mode?'개 본문':'건'} · ${first.channel_count}개 채널`:'선택 범위에 데이터 없음';
  $('updated').textContent=`마지막 수집 ${localTime(data.meta.collected_at_utc)} KST${data.meta.packaged_sample?' · 초기 샘플':''}`;
  const top=r.slice(0,3).map(x=>`<strong>${escape(x.entity)} ${num(x.count)}${mode?'개 본문':'건'}</strong>`).join(', ');
  $('brief').innerHTML=first?`${top}의 언급이 많습니다. 현재 선택한 범위에서 종목 언급을 확인한 메시지는 <strong>${num(s.counted_posts)}건</strong>입니다. 원시 횟수와 유사 본문을 함께 비교하면 반복 게시의 영향을 구분할 수 있습니다.`:'선택 범위에 집계할 종목 언급이 없습니다. 날짜·채널·분류 필터를 조정하세요.';
  const sampleEnd=data.meta.end_exclusive_kst.slice(0,10), captured=localTime(data.meta.collected_at_utc).slice(0,10);
  const outside=data.filters.start<data.meta.start_kst.slice(0,10)||data.filters.end>=sampleEnd;
  $('coverage').textContent=`조회 ${data.filters.start} ~ ${data.filters.end} KST${outside?' · 저장된 기간 밖 데이터 미수집':''}${data.filters.start<=captured&&data.filters.end>=captured?' · '+captured+' 부분 일자':''}`;
  $('rank-mode').textContent=mode?'유사 본문 기준':'게시물 기준';
  $('rankings').innerHTML=r.length?r.slice(0,10).map((x,i)=>`<button class="rank-row" data-entity="${escape(x.entity)}"><span class="rank-index">${String(i+1).padStart(2,'0')}</span><span class="rank-name">${escape(x.entity)}<span class="rank-meta">${x.channel_count}개 채널 · 원시 ${x.raw}건 / 본문 ${x.clusters}개${x.list?' · 목록 '+x.list+'건':''}</span></span><span class="rank-bar"><span style="width:${100*x.count/first.count}%"></span></span><span class="rank-count">${x.count}<small>${mode?'개':'건'}</small></span></button>`).join(''):'<p class="empty">언급 데이터가 없습니다.</p>';
  $('cloud').innerHTML=r.length?r.slice(0,30).map(x=>`<button data-entity="${escape(x.entity)}" style="font-size:${Math.round(13+27*Math.sqrt(x.count/first.count))}px" title="${escape(x.entity)}: ${x.count}${mode?'개 본문':'건'}">${escape(x.entity)}</button>`).join(''):'<p class="empty">선택 범위에 종목이 없습니다.</p>';
  renderChart(data); renderChannels(data); renderIssues(data);
  if(typeof managerState!=='undefined'&&managerState)renderManager(managerState);
}
function chartMarkup(data) {
  if(!data.timeline.length||!data.timeline.some(s=>s.values.some(v=>v)))return '<p class="empty">표시할 언급 추이가 없습니다.</p>';
  const W=700,H=245,L=35,T=14,R=14,B=38, width=W-L-R,height=H-T-B;
  const max=Math.max(1,...data.timeline.flatMap(s=>s.values));
  const ymax=Math.max(4,Math.ceil(max/4)*4);
  const x=i=>L+(data.dates.length===1?width/2:i*width/(data.dates.length-1));
  const y=v=>T+height-v/ymax*height;
  let svg=`<svg viewBox="0 0 ${W} ${H}" role="img" aria-label="종목별 일자별 언급 추이. 정확한 값은 아래 수치 표에서 확인할 수 있습니다.">`;
  for(let i=0;i<=4;i++) {const v=ymax*i/4;svg+=`<line class="gridline" x1="${L}" x2="${W-R}" y1="${y(v)}" y2="${y(v)}"/><text x="${L-9}" y="${y(v)+4}" text-anchor="end">${v}</text>`;}
  const partial=localTime(data.meta.collected_at_utc).slice(0,10);
  data.dates.forEach((d,i)=>{if(data.dates.length<=10||i%Math.ceil(data.dates.length/8)===0||i===data.dates.length-1)svg+=`<text x="${x(i)}" y="${H-13}" text-anchor="middle">${escape(d.slice(5).replace('-','/'))}${d===partial?'*':''}</text>`;});
  data.timeline.forEach((series,i)=>{
    const segments=[];let segment=[];
    series.values.forEach((v,j)=>{if(v===null){if(segment.length)segments.push(segment);segment=[];}else segment.push(`${x(j)},${y(v)}`);});
    if(segment.length)segments.push(segment);
    segments.forEach(points=>{svg+=`<polyline points="${points.join(' ')}" fill="none" stroke="${colors[i%5]}" stroke-width="2.2" stroke-linejoin="round"/>`;});
    series.values.forEach((v,j)=>{if(v!==null)svg+=`<circle cx="${x(j)}" cy="${y(v)}" r="3.4" fill="${colors[i%5]}"><title>${escape(series.entity)} · ${data.dates[j]} · ${v}${data.filters.mode==='clusters'?'개 본문':'건'}</title></circle>`;});
  });return svg+'</svg>';
}
function chartTable(data) {
  return `<table><thead><tr><th>종목</th>${data.dates.map(d=>`<th>${d.slice(5)}</th>`).join('')}</tr></thead><tbody>${data.timeline.map(s=>`<tr><th>${escape(s.entity)}</th>${s.values.map(v=>`<td>${v===null?'미수집':v}</td>`).join('')}</tr>`).join('')}</tbody></table>`;
}
function renderChart(data) {
  $('legend').innerHTML=data.timeline.map((s,i)=>`<span><i style="--series:${colors[i%5]}"></i>${escape(s.entity)}</span>`).join('');
  $('chart').innerHTML=chartMarkup(data); $('chart-table').innerHTML=chartTable(data);
  $('chart-note').textContent=(data.filters.mode==='clusters'?'중복 제거: 각 종목·본문 군집의 선택 범위 내 첫 게시일에 1회 반영합니다.':'같은 게시물의 같은 종목은 1회 집계합니다.')+' * 수집일은 부분 일자입니다. 기간 밖은 미수집으로 표시합니다.';
}
function renderChannels(data) {
  const max=Math.max(1,...data.channels.map(c=>c.posts));
  $('channels').innerHTML=data.channels.map(c=>`<div class="channel-card"><header><strong>${escape(c.name)}</strong><strong>${num(c.posts)}건</strong></header><div class="bar"><span style="width:${100*c.posts/max}%"></span></div><p>종목/기업 ${c.entities}개 · 전달 ${c.forwarded}건 · 고정 ${c.pins}건</p><p>${c.first?`${localTime(c.first)} ~ ${localTime(c.last).slice(5)}`:(c.coverage_complete?'확보한 기간의 메시지 없음':'선택 기간 미수집 또는 경계 미확인')}</p><p>${c.coverage_complete?'선택 기간 수집 이력 확인':'선택 기간 미수집·경계 미확인'}${c.collected_at_utc&&!c.last_attempt_complete?' · 최근 시도는 일부 수집':''}${c.collected_at_utc?' · 확인 '+localTime(c.collected_at_utc).slice(11)+' KST':''}</p></div>`).join('');
}
function issueMarkup(issue) {
  return `<article class="issue-card"><h3>${issue.entities.map(e=>`<button data-entity="${escape(e)}">${escape(e)}</button>`).join(' · ')}</h3><p>${escape(issue.issue)}</p><div class="issue-links">${issue.links.slice(0,4).map(u=>link(u,u.split('/').slice(-2).join('/'))).join('')}</div><small>범위 내 근거 ${issue.links.length}건 / 전체 샘플 근거 ${issue.sample_source_count}건</small></article>`;
}
function renderIssues(data) {$('issues').innerHTML=data.issues.length?data.issues.map(issueMarkup).join(''):'<p class="empty">현재 범위와 연결된 사전 작성 이슈가 없습니다. 하단에서 원문 메시지를 확인하세요.</p>';}
async function loadPosts() {
  if(!applied)return;
  const id=++tableId;
  $('entity-filter').hidden=!entity; $('entity-filter').querySelector('span').textContent=entity?`선택 종목: ${entity}`:'';
  try {
    const data=await api('/api/posts?'+params(applied,{query:$('search').value,entity,kind,page}));
    if(id!==tableId)return;
    $('explorer-total').textContent=`${num(data.total)}건`;
    $('posts').innerHTML=data.items.length?data.items.map(p=>`<tr><td>${p.is_pin_notice?'<span class="pill">고정 알림</span>':''}${p.duplicate_count>1?`<span class="pill repeat">반복 ${p.duplicate_count}건</span>`:''}${p.list?'<span class="pill">목록</span>':''}${p.forwarded_from?'<span class="pill">전달</span>':''}${!p.is_pin_notice&&p.duplicate_count<2&&!p.list&&!p.forwarded_from?'<span class="pill">일반</span>':''}</td><td><div class="post-tags">${p.entities.slice(0,5).map(e=>`<button data-entity="${escape(e)}">${escape(e)}</button>`).join('')}${p.entities.length>5?`<span class="pill">+${p.entities.length-5}</span>`:''}${p.entities.length?'':'<span class="rank-meta">사전 내 언급 없음</span>'}</div></td><td><div class="post-preview">${p.text?escape(p.text):'텍스트 본문 없음 · 이미지/첨부 전용 메시지'}</div></td><td>${escape(channelNames[p.channel])}</td><td class="post-time">${localTime(p.datetime_kst).replace(' ','<br>')}</td><td><button class="detail-btn" data-post="${p.channel}/${p.id}">상세 보기</button><button class="ai-summary-action" data-ai-post="${p.channel}/${p.id}">✨ AI 요약</button><span class="source-link">${link(p.url,'원문')}</span></td></tr>`).join(''):'<tr><td colspan="6" class="empty">조건에 맞는 메시지가 없습니다. 검색어 또는 필터를 조정하세요.</td></tr>';
    const pages=Math.max(1,Math.ceil(data.total/data.page_size));
    $('page-info').textContent=`${page} / ${pages} 페이지 · ${data.total?((page-1)*data.page_size+1)+'–'+Math.min(page*data.page_size,data.total):'0'} / ${num(data.total)}건`;
    $('prev').disabled=page<=1; $('next').disabled=page>=pages;
  }catch(err){if(id===tableId)showError(err.message);}
}
function openDialog(title, html) { $('detail-title').textContent=title; $('detail-body').innerHTML=html; if(!$('detail').open)$('detail').showModal(); }
async function openEntity(name) {
  if(!applied)return;
  const id=++modalId;
  openDialog(name+' · 언급 근거','<p class="empty">언급 데이터를 불러오는 중입니다.</p>');
  try {
    const [data,messages]=await Promise.all([api('/api/dashboard?'+params(applied,{focus:name})),api('/api/posts?'+params(applied,{entity:name,page_size:8}))]);
    if(id!==modalId||!$('detail').open)return;
    const rank=data.ranking.find(r=>r.entity===name);
    if(!rank){$('detail-body').innerHTML='<p class="empty">선택한 필터에 이 기업의 언급이 없습니다.</p>';return;}
    $('detail-body').innerHTML=`<button class="ai-summary-action" data-ai-entity="${escape(name)}">✨ 이 종목 AI 종합 브리프</button><div class="detail-kpis"><span><b>${rank.raw}</b>언급 게시물</span><span><b>${rank.clusters}</b>유사 본문</span><span><b>${rank.channel_count}</b>채널</span><span><b>${rank.frequency_pct}%</b>전체 메시지 대비</span></div><p class="card-hint">첫 줄 언급 ${rank.headline}건 · 목록 ${rank.list}건 · 빈도의 분모는 선택 범위 전체 메시지 ${data.stats.posts}건입니다.</p><div class="chart-wrap">${chartMarkup(data)}</div><details class="chart-data"><summary>차트 수치 표로 보기</summary><div class="table-responsive">${chartTable(data)}</div></details><div class="detail-section"><h3>관련 이슈 · 주장 요약</h3><p class="card-hint">전체 샘플에서 작성한 요약이며, 선택 범위의 근거 링크만 표시합니다.</p>${data.issues.length?data.issues.map(i=>`<p>${escape(i.issue)}</p><div class="issue-links">${i.links.slice(0,5).map(u=>link(u,u.split('/').slice(-2).join('/'))).join('')}</div>`).join('<br>'):'<p>별도 작성된 이슈 요약이 없습니다. 아래 원문에서 문맥을 확인하세요.</p>'}</div><div class="detail-section"><h3>최근 언급 메시지</h3>${messages.items.map(p=>`<div class="message-body"><button class="detail-btn" data-post="${p.channel}/${p.id}">${escape(channelNames[p.channel])} · ${localTime(p.datetime_kst)} · 상세 보기 ↗</button>${escape(p.text.slice(0,190))}<br>${link(p.url,'Telegram 원문')}</div>`).join('')}</div><button class="btn-primary" data-explore="${escape(name)}">이 종목의 전체 메시지 ${messages.total}건 보기 →</button>`;
  }catch(err){if(id===modalId)$('detail-body').textContent=err.message;}
}
async function openPost(path) {
  const id=++modalId;
  openDialog('메시지 상세','<p class="empty">원문 데이터를 불러오는 중입니다.</p>');
  try {
    const p=await api('/api/post/'+path);
    if(id!==modalId||!$('detail').open)return;
    $('detail-title').textContent=channelNames[p.channel]+' · '+p.id;
    $('detail-body').innerHTML=`<p>${localTime(p.datetime_kst)} KST · ${link(p.url,'Telegram 원문')}</p><button class="ai-summary-action" data-ai-post="${p.channel}/${p.id}">✨ 메시지 AI 3줄 요약</button>${p.forwarded_from?`<p>전달 출처: ${escape(p.forwarded_from)}</p>`:''}<div class="post-tags">${p.mentions.map(m=>`<button data-entity="${escape(m.entity)}">${escape(m.entity)}</button>`).join('')}</div><div class="message-body">${escape(p.text||'텍스트 본문이 없습니다. 이미지/첨부는 Telegram 원문에서 확인하세요.')}</div><div class="detail-section"><h3>유사 본문 군집 ${escape(p.duplicate_cluster)} · 저장된 전체 범위 ${p.duplicates.length}건</h3><p class="card-hint">본문이 같은 메시지 묶음입니다. 독립 사건 수를 의미하지 않습니다.</p><div class="duplicate-links">${p.duplicates.map(d=>link(d.url,channelNames[d.channel]+'/'+d.url.split('/').pop())).join('')}</div></div><div class="detail-section"><h3>본문에 포함된 외부 링크</h3><div class="duplicate-links">${p.links.filter(u=>u?.startsWith('https://')).slice(0,12).map((u,i)=>link(u,`링크 ${i+1}`)).join('')||'외부 링크 없음'}</div></div><p class="card-hint">게시물의 주장은 사실 검증 전입니다. 본문·링크는 수집 당시 저장된 내용입니다.</p>`;
  }catch(err){if(id===modalId)$('detail-body').textContent=err.message;}
}
function showMethod() {
  ++modalId;
  openDialog('집계 기준과 수집 범위',`<div class="detail-section"><h3>언급 게시물 수</h3><p>같은 메시지에서 같은 종목은 1회 집계합니다. 종목별 빈도(%)는 언급 게시물 수를 선택 범위 전체 수집 메시지 수로 나눈 값입니다. 여러 종목이 함께 나오므로 종목별 빈도의 합은 100%를 넘을 수 있습니다.</p></div><div class="detail-section"><h3>유사 본문 중복 제거</h3><p>공백·제로폭 문자 제거와 대소문자 통일 후 동일 본문, 또는 100자 이상·길이 차이 10% 이하·유사도 0.94 이상 본문을 묶습니다. 채널을 가로질러 집계하며, 필터를 적용한 뒤 각 종목·군집을 1회 셉니다. 일별 값은 선택 범위 안의 첫 게시일에 반영합니다.</p></div><div class="detail-section"><h3>목록과 분석 대상</h3><p>미래에셋 퀀트 Daily와 반도체 밸류 체인 시세 글을 종목 목록으로 구분합니다. 첫 줄 언급은 주요 분석 대상의 참고 지표이며, 제목 위치나 주변 기업 비교 때문에 오차가 있습니다. 전달 글도 별도 메시지로 세되 본문 중복을 따로 확인합니다.</p></div><div class="detail-section"><h3>현재 저장 범위</h3><p>${current?escape(current.meta.start_kst.slice(0,10))+' ~ '+escape(new Date(new Date(current.meta.end_exclusive_kst.slice(0,10)+'T00:00:00Z').getTime()-86400000).toISOString().slice(0,10)):'불러오는 중'} KST. 채널마다 확보한 기간이 다르며 채널 관리에서 수집 경계를 확인하세요. 오늘은 수집 시점까지의 부분 일자입니다. 공개 웹 응답만 수집했으며 삭제·비공개 메시지, 이미지·PDF·영상 내부 및 링크 목적지 본문은 제외했습니다. 기간 밖을 조회해도 미수집 날짜에는 데이터가 없습니다.</p></div><div class="detail-section"><h3>해석의 한계</h3><p>샘플 종목 사전 기준이며 모든 종목을 전수 탐지한 결과는 아닙니다. 상장·티커 미검증 기업은 별도 선택으로 포함합니다. 게시물의 주장과 검증된 사실을 구분하며 비교 기간을 수집하지 않아 증가율은 표시하지 않습니다.</p></div><div class="detail-section"><h3>데이터 갱신</h3><p>기본 조회는 KST 오늘까지 최근 7일입니다. 최신 데이터 수집은 활성 채널 전체를 Telegram에서 실제 수집하고 최근 7일로 이동합니다. 자동·예약 수집은 없으며 앱을 다시 열거나 저장 데이터를 다시 읽는 것만으로 새 글을 가져오지 않습니다. 채널 관리에서 공개 채널을 등록하고 원하는 시작일·종료일을 지정해 선택 기간 수집을 실행하세요. 백그라운드에서 수집·분석하며 완료 후 자동 반영합니다. 비활성화는 메시지를 삭제하지 않습니다.</p></div>`);
}
document.addEventListener('click',event=>{
  const element=event.target.closest('[data-entity],[data-post],[data-explore]');if(!element)return;
  if(element.dataset.entity)openEntity(element.dataset.entity);
  else if(element.dataset.post)openPost(element.dataset.post);
  else {entity=element.dataset.explore;page=1;kind='all';$('search').value='';updateKinds();$('detail').close();++modalId;loadPosts();$('explorer').scrollIntoView({behavior:'smooth',block:'start'});}
});
function updateKinds() {document.querySelectorAll('[data-kind]').forEach(b=>b.classList.toggle('active',b.dataset.kind===kind));}
function reset() {
  $('start').value=config.start;$('end').value=config.end;
  document.querySelectorAll('[name=channel]').forEach(c=>c.checked=true);$('mode').value='posts';$('exclude-pins').checked=true;$('exclude-lists').checked=false;$('other').checked=false;
  kind='all';entity='';$('search').value='';updateKinds();loadDashboard();
}
document.addEventListener('DOMContentLoaded',async()=>{
  try{setTheme(localStorage.getItem('telegram-theme')!=='dark');}catch{setTheme(true);}
  try {
    config=await api('/api/config');
    channelNames=Object.fromEntries(config.channels.map(c=>[c.id,c.name]));
    $('channel-options').innerHTML=config.channels.map(c=>`<label><input type="checkbox" name="channel" value="${escape(c.id)}" checked> ${escape(c.name)}</label>`).join('');
    $('start').value=config.start;$('end').value=config.end;
  } catch(err) {showError('채널 설정을 읽을 수 없습니다. '+err.message);return;}
  const saved=new URLSearchParams(location.search);
  ['start','end','mode'].forEach(id=>{if(saved.has(id))$(id).value=saved.get(id);});
  if(saved.has('channels'))document.querySelectorAll('[name=channel]').forEach(c=>c.checked=saved.get('channels').split(',').includes(c.value));
  if(config.channels.length&&!document.querySelector('[name=channel]:checked'))document.querySelectorAll('[name=channel]').forEach(c=>c.checked=true);
  if(saved.has('exclude_pins'))$('exclude-pins').checked=saved.get('exclude_pins')==='true';
  if(saved.has('exclude_lists'))$('exclude-lists').checked=saved.get('exclude_lists')==='true';
  $('other').checked=saved.get('scope')==='all';
  $('filters').addEventListener('submit',e=>{e.preventDefault();loadDashboard();});
  ['mode','exclude-pins','exclude-lists','other'].forEach(id=>$(id).addEventListener('change',loadDashboard));
  $('theme').addEventListener('click',()=>setTheme(!document.body.classList.contains('theme-light')));
  $('reset').addEventListener('click',reset);$('method').addEventListener('click',showMethod);
  $('export').addEventListener('click',()=>{if(applied)location.href='/api/export?'+params(applied);});
  $('reload').addEventListener('click',async()=>{
    $('reload').disabled=true;$('reload').textContent='저장 데이터 읽는 중…';
    try{await api('/api/reload',{method:'POST'});await loadDashboard();notify('저장된 분석 결과를 다시 읽었습니다.');}catch(err){showError(err.message);}
    finally{$('reload').disabled=false;$('reload').textContent='저장 데이터 다시 읽기';}
  });
  $('search').addEventListener('input',()=>{clearTimeout(searchTimer);searchTimer=setTimeout(()=>{page=1;loadPosts();},250);});
  $('kinds').addEventListener('click',e=>{const b=e.target.closest('[data-kind]');if(b){kind=b.dataset.kind;page=1;updateKinds();loadPosts();}});
  $('prev').addEventListener('click',()=>{page=Math.max(1,page-1);loadPosts();});$('next').addEventListener('click',()=>{page++;loadPosts();});
  $('entity-filter').querySelector('button').addEventListener('click',()=>{entity='';page=1;loadPosts();});
  $('close-detail').addEventListener('click',()=>{$('detail').close();++modalId;});
  $('detail').addEventListener('cancel',()=>++modalId);
  $('detail').addEventListener('click',e=>{if(e.target===$('detail')){const r=$('detail').getBoundingClientRect();if(e.clientX<r.left||e.clientX>r.right||e.clientY<r.top||e.clientY>r.bottom){$('detail').close();++modalId;}}});
  loadDashboard();
});
