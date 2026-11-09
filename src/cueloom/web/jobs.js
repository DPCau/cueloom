import {request, upload} from './api.js';
import {$, el, badge, labels, kv, bytes, time, empty, button, action, notice, report} from './ui.js';
let selected = null;
let uploaded = null;
let chosenFile = null;
let uploading = false;
let submitting = false;
let detailVersion = 0;
let lastJobs = [];
const stages = ['asr','segment','translate','qc','emit'];

function choose(file) {
  if (uploading || !file) return;
  chosenFile = file;
  uploaded = null;
  $('file-info').textContent = `${file.name} · ${bytes(file.size)}`;
  $('upload-label').textContent = '待上传';
  $('upload-progress').value = 0;
}
function options(demo) {
  if (!$('run-form').reportValidity()) return null;
  const formats = [...document.querySelectorAll('input[name="format"]:checked')].map((n) => n.value);
  if (!formats.length) throw new Error('请至少选择一种字幕格式。');
  if (!demo && !uploaded) throw new Error('请先上传素材，上传成功后再创建真实任务。');
  return {upload_id:demo ? null : uploaded.upload_id, target_lang:$('target-lang').value.trim(), bilingual:$('bilingual').checked, formats, demo};
}
async function submit(demo) {
  if (submitting) return;
  const payload = options(demo);
  if (!payload) return;
  if (demo && !window.confirm('Demo 将生成假文本，不是真实识别或翻译，也不使用上传素材。确认运行演示？')) return;
  submitting = true;
  $('submit-job').disabled = $('demo-button').disabled = true;
  try {
    const result = await request('/api/jobs', {method:'POST', body:payload});
    selected = result.job_id;
    notice(demo ? 'Demo 已创建：使用假文本，非真实识别。' : '真实任务已创建，正在后台处理。', true);
    location.hash = 'jobs';
    await refreshJobs();
  } finally {
    submitting = false;
    $('submit-job').disabled = $('demo-button').disabled = false;
  }
}
export function initJobs() {
  $('media-file').addEventListener('change', (event) => choose(event.target.files[0]));
  const zone = $('dropzone');
  zone.addEventListener('dragover', (event) => { event.preventDefault(); if (!uploading) zone.classList.add('dragging'); });
  zone.addEventListener('dragleave', () => zone.classList.remove('dragging'));
  zone.addEventListener('drop', (event) => { event.preventDefault(); zone.classList.remove('dragging'); choose(event.dataTransfer.files[0]); });
  $('upload-button').addEventListener('click', () => action($('upload-button'), async () => {
    if (!chosenFile || !chosenFile.size) throw new Error('请选择非空音视频文件。');
    if (!/\.(mp4|mkv|mov|wav|mp3|m4a|flac|webm|ogg)$/i.test(chosenFile.name)) throw new Error('不支持此文件格式，请选择列表中的音视频文件。');
    uploaded = null;
    uploading = true;
    $('media-file').disabled = true;
    $('upload-label').textContent = '上传中…';
    try {
      uploaded = await upload(chosenFile, (done, total) => {
        if (total) {
          const percent = Math.round(done / total * 100);
          $('upload-progress').value = percent;
          $('upload-label').textContent = percent === 100 ? '传输完成，服务端校验中…' : `上传中 ${percent}% · ${bytes(done)} / ${bytes(total)}`;
        } else {
          $('upload-progress').removeAttribute('value');
          $('upload-label').textContent = `已传输 ${bytes(done)}`;
        }
      });
      $('upload-progress').value = 100;
      $('upload-label').textContent = `上传成功 · ${bytes(uploaded.size)}`;
    } catch (error) {
      $('upload-label').textContent = '上传失败，请重新上传';
      $('upload-progress').value = 0;
      throw error;
    } finally { uploading = false; $('media-file').disabled = false; }
  }));
  $('run-form').addEventListener('submit', (event) => { event.preventDefault(); action($('submit-job'), () => submit(false)); });
  $('demo-button').addEventListener('click', () => action($('demo-button'), () => submit(true)));
  $('jobs-refresh').addEventListener('click', () => action($('jobs-refresh'), refreshJobs));
}
function selectJob(id) {
  selected = id;
  renderList(lastJobs);
  location.hash = 'jobs';
  loadDetail().catch(report);
}
function renderList(jobs) {
  const list = $('jobs-list');
  list.replaceChildren();
  if (!jobs.length) empty(list, '暂无任务。前往「运行」制作第一份字幕。');
  for (const job of jobs) {
    const item = button('', () => selectJob(job.job_id), `job-item${selected === job.job_id ? ' selected' : ''}`);
    const head = el('div', null, 'actions');
    head.append(badge(job.status), el('span', job.target_lang, 'muted'));
    if (job.demo) head.append(el('span', 'Mock 演示', 'badge'));
    item.append(head, el('div', job.job_id, 'mono'), el('small', time(job.created_at)));
    list.append(item);
  }
}
function recent(jobs) {
  const container = $('recent-jobs');
  if (!jobs.length) { empty(container, '尚无制作记录，创建任务后将在这里显示。'); return; }
  const wrap = el('div', null, 'table-wrap');
  const table = el('table');
  const head = el('tr');
  for (const title of ['任务','状态','阶段','目标语言','创建时间']) head.append(el('th', title));
  const thead = el('thead'); thead.append(head);
  const tbody = el('tbody');
  for (const job of jobs.slice(0,5)) {
    const row = el('tr');
    const id = el('td'); id.append(button(job.job_id.slice(0,12), () => selectJob(job.job_id), 'quiet mono'));
    const status = el('td'); status.append(badge(job.status));
    row.append(id, status, el('td', labels[job.stage] || job.stage || '等待'), el('td', job.target_lang), el('td', time(job.created_at)));
    tbody.append(row);
  }
  table.append(thead, tbody); wrap.append(table); container.replaceChildren(wrap);
}
export async function refreshJobs() {
  const [jobs, active] = await Promise.all([request('/api/jobs'), request('/api/jobs/active')]);
  jobs.sort((a,b) => String(b.created_at).localeCompare(String(a.created_at)));
  lastJobs = jobs;
  if (!selected && jobs.length) selected = active.job_id || jobs[0].job_id;
  renderList(jobs);
  recent(jobs);
  const running = $('active-job');
  running.className = '';
  if (active.job) {
    const status = el('div'); status.append(badge(active.job.status));
    running.replaceChildren(status, el('p', active.job_id, 'mono'), el('p', `当前阶段：${labels[active.job.stage] || active.job.stage || '准备中'}`), button('查看详情 →', () => selectJob(active.job_id)));
  } else empty(running, '当前没有运行中的流水线。');
  if (selected) await loadDetail();
  return jobs;
}
async function download(id, artifact) {
  const blob = await request(`/api/jobs/${encodeURIComponent(id)}/artifacts/${encodeURIComponent(artifact.name)}`, {blob:true});
  const url = URL.createObjectURL(blob);
  const link = el('a'); link.href = url; link.download = artifact.name;
  document.body.append(link); link.click(); link.remove();
  setTimeout(() => URL.revokeObjectURL(url), 30000);
}
async function loadDetail() {
  const id = selected;
  const version = ++detailVersion;
  const [job, artifacts] = await Promise.all([request(`/api/jobs/${encodeURIComponent(id)}`), request(`/api/jobs/${encodeURIComponent(id)}/artifacts`)]);
  if (version !== detailVersion || selected !== id) return;
  const container = $('job-detail'); container.className = '';
  const heading = el('div', null, 'actions'); heading.append(badge(job.status), el('span', id, 'mono'));
  const info = el('dl', null, 'kv-list');
  kv(info, [['目标语言', job.target_lang], ['源语言', job.source_lang || '自动检测'], ['字幕格式', (job.formats || []).join(' / ').toUpperCase()], ['双语', job.bilingual ? '是' : '否'], ['创建时间', time(job.created_at)]]);
  container.replaceChildren(heading, info);
  if (job.demo) container.append(el('div', 'Mock 演示：以下字幕是假文本，不代表真实识别或翻译质量。', 'callout'));
  if (job.resume_hint) container.append(el('div', job.resume_hint, 'callout'));
  if (['failed','interrupted'].includes(job.status)) container.append(el('p', '任务未完成，请检查阶段结果、模型资源与配置。', 'error-text'));
  const timeline = el('ol', null, 'stage-list');
  const results = job.stage_results || [];
  for (const stage of stages) {
    const result = results.find((item) => item.stage === stage);
    const row = el('li');
    const current = stage === job.stage;
    row.append(badge(result ? (result.ok ? 'done' : 'failed') : current && job.status === 'running' ? 'running' : current && job.status === 'failed' ? 'failed' : '待处理'));
    const content = el('div'); content.append(el('b', labels[stage]));
    if (result) content.append(el('small', `${result.count ?? 0} 条 · ${Number(result.duration_sec || 0).toFixed(2)} 秒`));
    for (const warning of result?.warnings || []) content.append(el('small', warning, 'error-text'));
    row.append(content); timeline.append(row);
  }
  container.append(timeline, el('h2', '字幕产物'));
  if (!artifacts.length) container.append(el('div', '暂无可下载字幕。任务完成后产物将自动出现在这里。', 'empty'));
  for (const artifact of artifacts) {
    const row = el('div', null, 'artifact');
    const text = el('div'); text.append(el('strong', artifact.name), el('small', `${String(artifact.format).toUpperCase()} · ${bytes(artifact.size)}`));
    row.append(text, button('下载', () => download(id, artifact))); container.append(row);
  }
}
