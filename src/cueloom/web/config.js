import {request} from './api.js';
import {$, el, action, notice, button} from './ui.js';
const names = {'llm.base_url':'API 根地址','llm.model':'模型名称','llm.api_key':'API key','llm.timeout_sec':'请求超时（秒）','llm.max_concurrency':'最大并发','llm.max_retries':'重试次数','llm.batch_max_items':'每批最大条目','llm.batch_max_tokens':'每批最大 Token','llm.context_window':'上下文窗口','llm.cache':'启用缓存','segment.max_cps':'最大阅读速度（字/秒）','segment.min_cps':'最小阅读速度（字/秒）','segment.max_chars_per_line':'每行最大字符数','segment.max_lines':'最大行数','segment.min_duration_sec':'最短显示时长（秒）','segment.max_duration_sec':'最长显示时长（秒）','output.bilingual':'默认双语字幕','output.formats':'默认字幕格式','output.bilingual_order':'双语排列顺序','output.max_cps_enforce':'强制阅读速度上限'};
let fields = [];
let configData = null;
let dirty = false;
export function configSnapshot() { return configData; }
export async function loadConfig(force = false) {
  if (dirty && !force) return;
  const data = await request('/api/config');
  render(data);
}
function render(data) {
  configData = data;
  fields = [];
  dirty = false;
  $('config-note').textContent = `${data.editable ? '配置可编辑。' : '当前部署配置只读。'} ${data.note || ''} 环境变量覆盖的字段不可编辑。`;
  $('config-save').disabled = !data.editable;
  const container = $('config-fields'); container.replaceChildren();
  const sections = new Map();
  for (const schema of data.schema) {
    const [section, key] = schema.key.split('.');
    if (['llm.base_url','llm.model','llm.api_key'].includes(schema.key)) continue;
    if (!sections.has(section)) {
      const card = el('section', null, 'card');
      card.append(el('h2', {llm:'语言模型 / LLM',segment:'字幕断句',output:'输出规范'}[section] || section));
      sections.set(section, card); container.append(card);
    }
    const wrapper = el('label', null, 'field');
    wrapper.append(el('span', names[schema.key] || schema.key));
    const value = data.config[section]?.[key];
    let input;
    if (schema.enum) {
      input = el('select');
      for (const option of schema.enum) {
        const node = el('option', {source_first:'原文在前',target_first:'译文在前'}[option] || option);
        node.value = option; input.append(node);
      }
      input.value = value ?? '';
    } else if (schema.type === 'list') {
      input = el('select'); input.multiple = true; input.size = 3;
      for (const format of ['srt','vtt','ass']) {
        const option = el('option', format.toUpperCase()); option.value = format;
        option.selected = (value || []).includes(format); input.append(option);
      }
      wrapper.append(el('small', '按住 Ctrl / Command 可多选，至少选择一种'));
    } else {
      input = el('input');
      input.type = schema.sensitive ? 'password' : schema.type === 'bool' ? 'checkbox' : ['int','float'].includes(schema.type) ? 'number' : 'text';
      if (schema.type === 'bool') input.checked = Boolean(value);
      else if (!schema.sensitive) input.value = value ?? '';
      if (schema.sensitive) {
        input.autocomplete = 'new-password';
        input.placeholder = data.config.llm?.api_key_configured ? '已配置；留空保留现有密钥' : '未配置；输入新密钥';
        input.spellcheck = false;
      }
      if (schema.range) {
        input.min = schema.range[0]; input.max = schema.range[1];
        input.step = schema.type === 'float' ? 'any' : '1';
      }
      if (schema.type === 'str') input.maxLength = schema.key === 'llm.model' ? 256 : 4096;
    }
    input.disabled = !data.editable || !schema.editable;
    input.id = `config-${schema.key.replaceAll('.', '-')}`;
    wrapper.htmlFor = input.id;
    const original = read(input, schema);
    input.addEventListener('input', () => { dirty = true; });
    input.addEventListener('change', () => { dirty = true; });
    wrapper.append(input);
    const hints = [`保存至 ${schema.target}`];
    if (schema.range) hints.push(`范围 ${schema.range.join('–')}`);
    if (schema.overridden_by_env) hints.push('被环境变量覆盖');
    if (!schema.editable && !schema.overridden_by_env) hints.push('只读');
    if (schema.restart_required) hints.push('需重启');
    wrapper.append(el('small', hints.join(' · ')));
    if (schema.sensitive) wrapper.append(el('small', '不回显密钥，空白不会提交；此界面不提供清空密钥操作。'));
    sections.get(section).append(wrapper);
    fields.push({schema, input, original});
  }
}
function read(input, schema) {
  if (schema.type === 'bool') return input.checked;
  if (schema.type === 'list') return [...input.selectedOptions].map((option) => option.value);
  if (['int','float'].includes(schema.type)) return input.value === '' ? null : Number(input.value);
  return input.value;
}
let editingProfile = null;
function resetProfile(item = null) {
  editingProfile = item?.id || null;
  $('profile-editor-title').textContent = item ? `编辑：${item.name}` : '新建配置方案';
  $('profile-name').value = item?.name || '';
  $('profile-url').value = item?.base_url || '';
  $('profile-model').value = item?.model || '';
  $('profile-key').value = '';
  $('profile-key').placeholder = item?.api_key_configured ? '已配置；留空保留已保存密钥' : '输入密钥（不回显）';
  $('profile-clear-key').checked = false;
}
export async function loadProfiles() {
  const data = await request('/api/llm/profiles');
  $('profiles-note').textContent = data.switchable ? '选择启用方案后，新任务使用该连接。没有启用标记时，当前连接为独立配置或方案已修改。' : '配置只读或连接被环境变量覆盖，当前不可切换。';
  for (const input of $('profile-form').querySelectorAll('input,button')) input.disabled = !data.editable;
  $('profile-new').disabled = !data.editable;
  const list = $('profile-list'); list.replaceChildren();
  if (!data.profiles.length) list.append(el('p', '尚无方案。可新建，或将当前连接导入为第一套方案。', 'muted'));
  for (const item of data.profiles) {
    const card = el('section', null, 'model-variant');
    card.append(el('h3', item.name), el('p', `${item.model} · ${item.base_url}`, 'mono'), el('small', `${item.active ? '当前启用 · ' : item.selected ? '已修改，需重新启用或先切换再删除 · ' : ''}密钥${item.api_key_configured ? '已保存' : '未配置'}`));
    const actions = el('div', null, 'actions');
    const activate = button(item.active ? '当前启用' : '启用方案', async () => {
      await request(`/api/llm/profiles/${item.id}/activate`, {method:'POST'});
      await loadConfig(true); await loadProfiles();
      $('probe-result').textContent = '方案已切换，尚未测试新连接';
      notice(`已启用 ${item.name}，仅对新任务生效。`, true);
      window.dispatchEvent(new Event('cueloom:config-updated'));
    });
    activate.disabled = item.active || !data.switchable;
    const edit = button('编辑', () => resetProfile(item)); edit.disabled = !data.editable;
    const remove = button('删除', async () => {
      if (!window.confirm(`删除配置方案“${item.name}”？该方案的已保存密钥也将移除。`)) return;
      await request(`/api/llm/profiles/${item.id}`, {method:'DELETE'});
      if (editingProfile === item.id) resetProfile();
      await loadProfiles();
    }, 'danger');
    remove.disabled = item.selected || !data.editable;
    actions.append(activate, edit, remove); card.append(actions); list.append(card);
  }
}
export function initConfig() {
  $('profile-new').addEventListener('click', () => resetProfile());
  $('profile-form').addEventListener('submit', (event) => {
    event.preventDefault();
    action($('profile-save'), async () => {
      const payload = {name:$('profile-name').value.trim(), base_url:$('profile-url').value.trim(), model:$('profile-model').value.trim()};
      if ($('profile-clear-key').checked) payload.api_key = '';
      else if ($('profile-key').value) payload.api_key = $('profile-key').value;
      await request(editingProfile ? `/api/llm/profiles/${editingProfile}` : '/api/llm/profiles', {method:editingProfile ? 'PUT' : 'POST', body:payload});
      resetProfile(); await loadProfiles();
      notice('方案已保存。点击启用后才会用于新任务。', true);
    });
  });
  $('profile-copy-current').addEventListener('click', () => action($('profile-copy-current'), async () => {
    const name = $('profile-name').value.trim();
    if (!name) throw new Error('请先填写导入方案名称。');
    await request('/api/llm/profiles/import-current', {method:'POST', body:{name}});
    resetProfile(); await loadProfiles(); notice('当前连接已保存为方案，密钥未返回浏览器。', true);
  }));
  $('config-form').addEventListener('submit', (event) => {
    event.preventDefault();
    action($('config-save'), async () => {
      const payload = {};
      for (const {schema, input, original} of fields) {
        if (input.disabled) continue;
        const value = read(input, schema);
        if (schema.sensitive && !value.trim()) continue;
        if (JSON.stringify(value) === JSON.stringify(original)) continue;
        if (value === null) throw new Error(`${names[schema.key] || schema.key}不能为空。`);
        if (schema.type === 'list' && !value.length) throw new Error('请至少选择一种默认字幕格式。');
        const [section, key] = schema.key.split('.');
        (payload[section] ||= {})[key] = value;
      }
      if (!Object.keys(payload).length) { notice('没有需要保存的修改，现有密钥保持不变。', true); return; }
      const result = await request('/api/config', {method:'PUT', body:payload});
      render(result);
      notice(result.overridden_by_env?.length ? `已保存，但字段被环境变量覆盖：${result.overridden_by_env.join('、')}` : '配置已保存，对下一次任务生效。', true);
      window.dispatchEvent(new Event('cueloom:config-updated'));
    });
  });
  $('config-reload').addEventListener('click', () => action($('config-reload'), async () => {
    if (dirty && !window.confirm('重新加载将丢弃尚未保存的表单修改，确认继续？')) return;
    render(await request('/api/config/reload', {method:'POST'}));
    notice('已从磁盘重新加载配置。', true);
    window.dispatchEvent(new Event('cueloom:config-updated'));
  }));
}
