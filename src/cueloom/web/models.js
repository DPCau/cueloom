import {request} from './api.js';
import {$, el, badge, kv, bytes, empty, button, action, notice} from './ui.js';
import {configSnapshot} from './config.js';
let tasks = [];
let models = [];
let loaded = false;
try { tasks = JSON.parse(sessionStorage.getItem('cueloom.model.tasks') || '[]'); if (!Array.isArray(tasks)) tasks = []; } catch { tasks = []; }
function persist() {
  try { sessionStorage.setItem('cueloom.model.tasks', JSON.stringify(tasks)); } catch { /* 存储不可用时保持内存轮询。 */ }
}
function running() { return tasks.some((task) => task.state === 'running'); }
function renderTasks() {
  const container = $('model-tasks'); container.replaceChildren();
  for (const task of tasks) {
    const card = el('article', null, 'card');
    const head = el('div', null, 'actions');
    head.append(badge(task.state), el('strong', `模型下载 · ${task.modelId}`));
    card.append(head, el('p', task.message || '后台下载中，完成后自动刷新模型列表。'));
    if (task.state === 'running') {
      const progress = el('progress');
      if (task.bytes_total > 0 && task.bytes_done != null) {
        progress.max = task.bytes_total; progress.value = task.bytes_done;
        card.append(el('small', `${bytes(task.bytes_done)} / ${bytes(task.bytes_total)}`, 'muted'));
      } else card.append(el('small', '后端尚未提供字节进度，显示不定进度；不代表下载停滞。', 'muted'));
      progress.setAttribute('aria-label', '模型后台下载进度'); card.append(progress);
    } else card.append(button('收起记录', () => { tasks = tasks.filter((item) => item.task_id !== task.task_id); persist(); renderTasks(); }));
    container.append(card);
  }
}
function renderModels() {
  const container = $('model-list'); container.replaceChildren();
  if (!models.length) empty(container, loaded ? '暂无可管理模型。' : '正在读取模型目录…');
  for (const model of models) {
    const card = el('article', null, 'card');
    const head = el('div', null, 'card-heading');
    head.append(el('h3', model.id), badge(model.state));
    const flags = el('div', null, 'actions');
    flags.append(el('span', model.kind === 'asr' ? '语音识别 / ASR' : '时间对齐 / ALIGN', 'badge'));
    if (model.is_default) flags.append(el('span', '当前默认', 'badge good'));
    const info = el('dl', null, 'kv-list');
    kv(info, [['本地体积', bytes(model.size_bytes)], ['托管状态', model.managed ? '注册模型' : '未托管'], ['运行支持', model.supported ? '支持' : '暂不支持'], ['许可证', model.license || '未声明']]);
    card.append(head, flags, info);
    for (const issue of model.issues || []) card.append(el('p', issue));
    const actions = el('div', null, 'actions');
    const download = button(model.state === 'partial' ? '继续下载' : '下载模型', async () => {
      const task = await request(`/api/models/${encodeURIComponent(model.id)}/download`, {method:'POST'});
      tasks.push({...task, modelId:model.id}); persist(); renderTasks(); renderModels();
      notice('下载已转入后台，可切换页面；完成后会自动更新模型状态。', true);
    });
    download.disabled = running() || !model.managed || model.status === 'deprecated' || model.state === 'complete';
    const use = button('设为默认', async () => {
      await request(`/api/models/${encodeURIComponent(model.id)}/default`, {method:'POST'});
      notice(`默认识别模型已切换为 ${model.id}，对下一次任务生效。`, true);
      window.dispatchEvent(new Event('cueloom:config-updated'));
      await refreshModels(true);
    });
    use.disabled = running() || model.is_default || !model.managed || !model.supported || model.kind !== 'asr' || model.state !== 'complete' || configSnapshot()?.editable === false;
    const remove = button('软删除', async () => {
      const confirm = window.prompt(`将模型移至服务端 models/.trash，不立即释放磁盘。\n请输入完整模型 ID 确认：${model.id}`);
      if (confirm === null) return;
      if (confirm !== model.id) throw new Error('确认文本不匹配，未执行删除。');
      await request(`/api/models/${encodeURIComponent(model.id)}`, {method:'DELETE', body:{confirm}});
      notice(`模型 ${model.id} 已移入回收目录。`, true);
      await refreshModels(true);
    }, 'danger');
    remove.disabled = running() || model.state === 'missing';
    actions.append(download, use, remove); card.append(actions); container.append(card);
  }
}
export async function refreshModels(force = false) {
  renderTasks();
  if (running()) { renderModels(); return; }
  if (force || !loaded || location.hash === '#models') {
    models = await request('/api/models'); loaded = true;
  }
  renderModels();
}
export async function pollModelTasks() {
  let finished = false;
  for (const task of tasks.filter((item) => item.state === 'running')) {
    try {
      const data = await request(`/api/tasks/${encodeURIComponent(task.task_id)}`);
      Object.assign(task, data);
      if (data.state !== 'running') {
        finished = true;
        notice(data.state === 'done' ? `模型 ${task.modelId} 下载完成。` : `模型 ${task.modelId} 下载失败：${data.message}`, data.state === 'done');
      }
    } catch (error) {
      if (error.status !== 404) throw error;
      task.state = 'interrupted'; task.message = '后台记录已不存在，服务可能已重启。请重新扫描模型状态。'; finished = true;
    }
  }
  persist(); renderTasks();
  if (finished) await refreshModels(true);
}
export function initModels() {
  renderTasks();
  $('models-rescan').addEventListener('click', () => action($('models-rescan'), async () => {
    if (running()) throw new Error('下载进行中，请等待后台下载结束后重新扫描。');
    models = await request('/api/models/rescan', {method:'POST'}); loaded = true; renderModels();
    notice('模型目录已重新扫描。', true);
  }));
}
