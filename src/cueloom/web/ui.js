export const $ = (id) => document.getElementById(id);
export function el(tag, text, className) {
  const node = document.createElement(tag);
  if (text !== undefined && text !== null) node.textContent = String(text);
  if (className) node.className = className;
  return node;
}
export function notice(message, success = false) {
  $('notice-text').textContent = message;
  $('notice').className = success ? 'notice success' : 'notice';
  $('notice').hidden = false;
}
export function report(error) { notice(error.message || '操作失败，请重试。'); }
export async function action(button, fn) {
  button.disabled = true;
  try { return await fn(); } catch (error) { report(error); } finally { button.disabled = false; }
}
export function button(text, fn, className = '') {
  const node = el('button', text, className);
  node.type = 'button';
  node.addEventListener('click', () => action(node, fn));
  return node;
}
export const labels = {created:'待处理', running:'运行中', completed:'已完成', done:'已完成', failed:'失败', interrupted:'已中断', missing:'未安装', partial:'不完整', complete:'已就绪', legacy:'旧版缓存', unmanaged:'未托管', asr:'语音识别', segment:'智能断句', translate:'语义翻译', qc:'质量检查', emit:'产物导出'};
export function badge(value) {
  const kind = ['complete','completed','done'].includes(value) ? 'good' : ['failed','interrupted'].includes(value) ? 'bad' : ['running','created'].includes(value) ? 'running' : '';
  return el('span', labels[value] || value || '未知', `badge ${kind}`);
}
export function kv(container, entries) {
  container.replaceChildren();
  for (const [key, value] of entries) {
    const row = el('div');
    row.append(el('dt', key), el('dd', value ?? '—'));
    container.append(row);
  }
}
export function bytes(value) {
  if (value == null) return '未知大小';
  if (value < 1024) return `${value} B`;
  const unit = value >= 1024 ** 3 ? 3 : value >= 1024 ** 2 ? 2 : 1;
  return `${(value / 1024 ** unit).toFixed(1)} ${['B','KB','MB','GB'][unit]}`;
}
export function time(value) {
  if (!value) return '时间未知';
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? String(value) : date.toLocaleString('zh-CN', {hour12:false});
}
export function empty(container, text) { container.replaceChildren(el('div', text, 'empty')); }
