let aiAvailable=false, aiBriefId=0;
async function initAI() {
  $('ai-brief').addEventListener('click',()=>openAI('brief'));
  try {
    const state=await api('/api/ai/status'); aiAvailable=state.available;
    $('ai-status').textContent=state.message+' · 저장된 공개 본문만 분석';
    $('ai-model').innerHTML=state.models.length?state.models.map(m=>`<option value="${escape(m)}">${escape(m)}</option>`).join(''):'<option value="">사용 가능한 모델 없음</option>';
    if(state.default_model)$('ai-model').value=state.default_model;
    $('ai-brief').disabled=!state.available;
  }catch(e){$('ai-status').textContent='AI 연결 확인 실패: '+e.message;}
}
function aiMarkup(data) {
  const items=(xs)=>xs.map(x=>`<li>${escape(x)}</li>`).join('');
  return `<div class="ai-output"><p class="ai-conclusion">${escape(data.one_line_summary)}</p><h3>AI 3줄 요약</h3><ol>${items(data.summary_lines)}</ol><h3>본문의 주요 논거</h3><ul>${items(data.investment_points)||'<li>본문에 명시 없음</li>'}</ul><h3>실적·밸류에이션 전망</h3><p>${escape(data.financial_outlook)}</p><h3>리스크·불확실성 · AI 해석</h3><ul>${items(data.risk_factors)||'<li>본문에 명시 없음</li>'}</ul><p class="ai-result-note">AI 생성 · ${escape(data.model)} · ${localTime(data.generated_at_utc)} KST · ${data.cached?'저장된 AI 결과':'새로 생성'}<br>요약 입력 ${data.source_count}건 / 조건에 맞는 본문 ${data.eligible_posts}건${data.input_truncated?' · 긴 본문 일부 생략':''}. 종합 브리프는 채널별 첫 줄 종목 언급을 우선하고 유사 본문을 제외한 최대 12건의 표본입니다. 첨부·링크 목적지 내부는 분석하지 않았습니다. AI 해석에는 추론·오류가 포함될 수 있으므로 원문에서 확인하세요.</p><div class="issue-links">${data.sources.map(p=>link(p.url,p.channel+'/'+p.url.split('/').pop())).join('')}</div></div>`;
}
async function openAI(kind,target='',refresh=false) {
  if(!aiAvailable){openDialog('AI 연결 안내','<p>로컬 Ollama를 실행하고 생성 모델을 준비한 뒤 페이지를 새로고침하세요. 저장된 이슈 요약은 AI 생성 결과가 아닙니다.</p>');return;}
  if(!applied)return;
  const model=$('ai-model').value;
  const filters={...applied};
  const title=kind==='post'?'메시지 AI 3줄 요약':kind==='entity'?target+' · AI 종합 브리프':'선택 범위 AI 브리프';
  const requestId=kind==='brief'?++aiBriefId:++modalId;
  const loading=`<p class="empty">로컬 AI (${escape(model)})가 요약을 생성하고 있습니다…</p>`;
  if(kind==='brief'){$('ai-result').innerHTML=loading;$('ai-brief').disabled=true;}else openDialog(title,loading);
  try {
    const path=kind==='post'?'/api/post/'+target+'/ai-summary':'/api/ai/brief?'+params(filters,kind==='entity'?{entity:target}:{});
    const data=await api(path,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({model,refresh})});
    if(kind==='brief'){
      if(requestId!==aiBriefId)return;
      $('ai-result').innerHTML=`<p class="ai-result-note">생성 범위 ${escape(filters.start)} ~ ${escape(filters.end)} · ${filters.channels.split(',').map(ch=>escape(channelNames[ch])).join(' / ')}</p>`+aiMarkup(data)+`<button class="ai-summary-action" data-ai-refresh="brief">↻ AI 다시 생성</button>`;
    }else if(requestId===modalId&&$('detail').open)$('detail-body').innerHTML=aiMarkup(data)+`<button class="ai-summary-action" data-ai-refresh="${kind}" data-ai-target="${escape(target)}">↻ AI 다시 생성</button>`;
  }catch(e){
    const html=`<p class="error-banner">${escape(e.message)}</p><button class="ai-summary-action" data-ai-refresh="${kind}" data-ai-target="${escape(target)}">AI 다시 시도</button>`;
    if(kind==='brief'&&requestId===aiBriefId)$('ai-result').innerHTML=html;
    else if(requestId===modalId&&$('detail').open)$('detail-body').innerHTML=html;
  }finally{if(kind==='brief'&&requestId===aiBriefId)$('ai-brief').disabled=!aiAvailable;}
}
document.addEventListener('DOMContentLoaded',initAI);
function clearAIBrief() {
  ++aiBriefId;
  $('ai-result').textContent='선택 범위가 갱신되었습니다. AI 브리프 버튼으로 현재 채널·기간의 요약을 생성하세요.';
  $('ai-brief').disabled=!aiAvailable;
}
document.addEventListener('click',event=>{
  const e=event.target.closest('[data-ai-post],[data-ai-entity],[data-ai-refresh]');
  if(!e)return;
  if(e.dataset.aiPost)openAI('post',e.dataset.aiPost);
  else if(e.dataset.aiEntity)openAI('entity',e.dataset.aiEntity);
  else openAI(e.dataset.aiRefresh,e.dataset.aiTarget||'',true);
});
