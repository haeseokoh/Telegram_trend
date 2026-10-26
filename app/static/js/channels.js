let channelPoll, knownJobs=null, managerState=null;
const jobLabels={queued:'대기',running:'수집 중',analyzing:'분석 중',completed:'완료',partial:'일부 수집 · 경계 미확인',failed:'실패',interrupted:'재시작으로 중단'};
const stopLabels={page_limit:'최대 페이지 도달',request_error:'네트워크 요청 실패',pagination_stalled:'페이지 진행 중단',no_public_messages:'공개 메시지 미확인'};
const busyJobs=jobs=>jobs.some(j=>['queued','running','analyzing'].includes(j.status));
async function refreshChannelConfig() {
  const previous=new Set([...document.querySelectorAll('[name=channel]')].map(c=>c.value));
  const chosen=new Set([...document.querySelectorAll('[name=channel]:checked')].map(c=>c.value));
  config=await api('/api/config');
  channelNames=Object.fromEntries(config.channels.map(c=>[c.id,c.name]));
  const checked=c=>chosen.has(c.id)||!previous.has(c.id);
  if(config.channels.length&&!config.channels.some(checked))chosen.add(config.channels[0].id);
  $('channel-options').innerHTML=config.channels.length?config.channels.map(c=>`<label><input type="checkbox" name="channel" value="${escape(c.id)}" ${checked(c)?'checked':''}> ${escape(c.name)}</label>`).join(''):'<p>활성 채널이 없습니다. 채널 관리에서 재활성화하세요.</p>';
  await loadDashboard();
}
function renderManager(state) {
  managerState=state;
  const busy=busyJobs(state.jobs);
  $('collect-latest').disabled=busy;
  $('collect-latest').textContent=busy?'Telegram 수집·분석 중…':'↻ 최신 데이터 수집';
  const batch=state.jobs.find(j=>j.kind==='refresh');
  const instruction='자동 수집은 꺼져 있습니다. 최신 데이터 수집은 활성 채널 전체를 Telegram에서 수집합니다. 화면 조회·저장 데이터 다시 읽기는 수집하지 않습니다.';
  const historical=config&&$('end').value<config.end?' 현재 과거 기간을 보고 있습니다. ‘최근 7일 보기’로 이동하세요.':'';
  $('refresh-status').textContent=instruction+(batch?` 최근 전체 갱신: ${jobLabels[batch.status]} · ${batch.completed_channels||0}/${batch.plans.length}채널${batch.finished_at_utc?' · '+localTime(batch.finished_at_utc)+' KST':''}${batch.new_posts!==undefined?' · 신규 '+num(batch.new_posts)+'건':''}${batch.error?' · '+batch.error:''}`:'')+historical;
  $('managed-channels').innerHTML=state.channels.map(c=>`<article class="managed-channel"><div><strong>${escape(c.name)}</strong><span class="pill">${c.enabled?'활성':'비활성'}</span><p>@${escape(c.id)} · 보존 메시지 ${num(c.stored_posts)}건</p><p>${c.coverage_ranges.length?c.coverage_ranges.map(r=>`${escape(r.start_kst.slice(0,10))} ~ ${escape(new Date(new Date(r.end_exclusive_kst.slice(0,10)+'T00:00:00Z').getTime()-86400000).toISOString().slice(0,10))} ${r.coverage_complete?'경계 확인':'일부 수집'}`).join('<br>'):'미수집 · 원하는 기간을 수집하세요.'}</p></div><div class="channel-actions"><button class="theme-toggle-btn" data-channel-toggle="${escape(c.id)}" data-enabled="${!c.enabled}">${c.enabled?'비활성화':'재활성화'}</button><button class="btn-primary" data-channel-collect="${escape(c.id)}" ${busy?'disabled':''}>선택 기간 수집</button></div></article>`).join('');
  $('collection-jobs').innerHTML=state.jobs.length?state.jobs.slice(0,15).map(j=>`<article class="collection-job"><strong>${escape(j.kind==='refresh'?'활성 채널 전체':channelNames[j.channel]||j.channel)} · ${escape(jobLabels[j.status]||j.status)}</strong><p>${escape(j.start)} ~ ${escape(j.end)} · HTML ${j.pages}페이지 · 경계 포함 ${num(j.retrieved_posts)}건${j.period_posts!==undefined?` · 기간 내 ${num(j.period_posts)}건`:''}${j.new_posts!==undefined?` · 신규 ${num(j.new_posts)}건`:''}</p>${j.oldest_kst?`<p>도달한 가장 오래된 글: ${escape(localTime(j.oldest_kst))} KST</p>`:''}${j.error?`<p class="job-error">${escape(j.error)}</p>`:''}${j.status==='partial'&&j.kind!=='refresh'?`<p class="job-error">${escape(stopLabels[j.stop_reason]||j.stop_reason)} · 미확인 기간은 완료로 표시하지 않습니다.</p>`:''}</article>`).join(''):'<p class="card-hint">아직 실행한 수집 작업이 없습니다.</p>';
}
async function pollChannels() {
  clearTimeout(channelPoll);
  try {
    const state=await api('/api/channels'); renderManager(state);
    const previous=knownJobs; knownJobs=new Map(state.jobs.map(j=>[j.id,j.status]));
    // CLI collection writes the same files but cannot publish this server's memory snapshot.
    if(!busyJobs(state.jobs)&&(!previous||state.jobs.some(j=>previous.has(j.id)&&previous.get(j.id)!==j.status))){
      await api('/api/reload',{method:'POST'});await refreshChannelConfig();
    }
    if(previous){
      const finished=state.jobs.filter(j=>previous.has(j.id)&&previous.get(j.id)!==j.status&&['completed','partial','failed','interrupted'].includes(j.status));
      if(finished.length){
        await refreshChannelConfig();
        for(const j of finished)notify(`${j.channel}: ${jobLabels[j.status]}${j.period_posts!==undefined?' · 기간 내 '+j.period_posts+'건':''}`);
      }
    }
    channelPoll=setTimeout(pollChannels,busyJobs(state.jobs)||$('channel-manager').open?2500:30000);
  }catch(e){$('manager-message').textContent=e.message;$('refresh-status').textContent='수집 상태 확인 실패: '+e.message;channelPoll=setTimeout(pollChannels,10000);}
}
async function channelAction(path,method,body) {
  return api(path,{method,headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
}
document.addEventListener('DOMContentLoaded',()=>{
  $('collect-latest').addEventListener('click',async()=>{
    $('collect-latest').disabled=true;
    try {
      const job=await channelAction('/api/collect-latest','POST',{});
      if(!knownJobs)knownJobs=new Map();knownJobs.set(job.id,'queued');
      await refreshChannelConfig();
      $('start').value=config.start;$('end').value=config.end;
      document.querySelectorAll('[name=channel]').forEach(c=>c.checked=true);
      await loadDashboard();await pollChannels();
      notify('활성 채널 전체 수집을 시작했습니다. 완료 후 분석 결과를 반영합니다. 서버는 켜 두세요.');
    }catch(e){showError(e.message);await pollChannels();}
  });
  $('recent-period').addEventListener('click',async()=>{
    try{config=await api('/api/config');$('start').value=config.start;$('end').value=config.end;await loadDashboard();await pollChannels();}
    catch(e){showError(e.message);}
  });
  $('manage-channels').addEventListener('click',()=>{
    $('collect-start').value=$('start').value;$('collect-end').value=$('end').value;
    $('manager-message').textContent='';$('channel-manager').showModal();pollChannels();
  });
  $('close-manager').addEventListener('click',()=>$('channel-manager').close());
  $('register-channel').addEventListener('submit',async e=>{
    e.preventDefault();$('register-channel-button').disabled=true;$('manager-message').textContent='Telegram 공개 미리보기를 확인하고 있습니다…';
    try {
      const added=await channelAction('/api/channels','POST',{channel:$('channel-input').value});
      $('channel-input').value='';$('manager-message').textContent=added.name+' 등록 완료. 아래에서 원하는 기간을 수집하세요.';
      await refreshChannelConfig();await pollChannels();
    }catch(err){$('manager-message').textContent=err.message;}
    finally{$('register-channel-button').disabled=false;}
  });
  $('managed-channels').addEventListener('click',async e=>{
    const b=e.target.closest('[data-channel-toggle],[data-channel-collect]');if(!b)return;
    b.disabled=true;
    try {
      if(b.dataset.channelToggle){
        await channelAction('/api/channels/'+b.dataset.channelToggle,'PATCH',{enabled:b.dataset.enabled==='true'});
        await refreshChannelConfig();$('manager-message').textContent='활성 설정을 저장했습니다. 기존 메시지는 보존됩니다.';
      }else{
        const start=$('collect-start').value,end=$('collect-end').value;
        if(!start||!end||start>end)throw new Error('수집 시작일과 종료일을 확인하세요.');
        const job=await channelAction('/api/channels/'+b.dataset.channelCollect+'/collect','POST',{start,end});
        if(!knownJobs)knownJobs=new Map();knownJobs.set(job.id,'queued');
        $('manager-message').textContent='수집을 시작했습니다. 창을 닫아도 진행되며 완료 후 분석 결과를 반영합니다.';
      }
      await pollChannels();
    }catch(err){$('manager-message').textContent=err.message;b.disabled=false;}
  });
  // Resume visibility of a background job after a browser reload.
  pollChannels();
});
