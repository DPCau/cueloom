import {request, setToken} from './api.js';
import {$, el, kv, action, notice, report} from './ui.js';
import {initJobs, refreshJobs} from './jobs.js';
import {initConfig, loadConfig, loadProfiles} from './config.js';
import {initModels, refreshModels, pollModelTasks} from './models.js';
const pages = ['overview','run','config','api','models','jobs'];
let authenticated = false;
let refreshing = false;
let authBusy = false;
let refreshDelay = 5000;
let lastAuth = null;

function openAuth(message = '') {
  $('auth-error').textContent = message;
  if (!$('auth-dialog').open) $('auth-dialog').showModal();
}
function setConnection(ok, text) {
  $('connection').textContent = text;
  $('connection').className = `badge ${ok ? 'good' : 'bad'}`;
}
function renderAuth(auth) {
  lastAuth = auth;
  authenticated = Boolean(auth.authenticated);
  $('auth-state').textContent = authenticated ? auth.local ? '本机已自动认证' : '远程 token 已认证' : '等待访问认证';
  kv($('api-auth'), [['认证方式', auth.local ? '本机回环自动认证' : 'Bearer token'], ['访问状态', authenticated ? '已认证' : '未认证'], ['服务端 token', auth.token_configured ? '已配置' : '未配置'], ['代理头信任', '不信任'], ['密码登录', '后端不支持']]);
}
async function authenticate() {
  const auth = await request('/api/auth');
  renderAuth(auth);
  if (!authenticated) {
    setConnection(false, '需要认证');
    openAuth('远程访问需要有效 token。若反复失败，请检查 HTTPS 与服务端 token 配置。');
    return false;
  }
  setConnection(true, '服务已连接');
  return true;
}
function renderOverview(status, jobs) {
  const c = status.config || {};
  const llm = c.llm || {};
  const service = c.service || {};
  const finished = jobs.filter((job) => ['completed','done'].includes(job.status)).length;
  const metrics = [['任务总数', jobs.length, '全部制作记录'], ['已完成', finished, '字幕交付记录'], ['处理中', jobs.filter((job) => ['created','running'].includes(job.status)).length, '单流水线运行'], ['服务版本', status.version ? `v${status.version}` : '—', `已运行 ${Math.floor((status.uptime_sec || 0) / 60)} 分钟`]];
  $('overview-metrics').replaceChildren(...metrics.map(([name, value, hint]) => {
    const card = el('article', null, 'metric'); card.append(el('span', name, 'muted'), el('strong', value), el('small', hint)); return card;
  }));
  kv($('environment'), [['识别模型', c.asr?.model || '未配置'], ['识别后端', c.asr?.backend || '未配置'], ['LLM 模型', llm.model || '未配置'], ['LLM 配置', llm.configured ? '配置完整（未探活）' : '未配置完整'], ['API key', llm.api_key_configured ? '已配置，不回显' : '未配置'], ['输出格式', (c.output?.formats || []).join(' / ').toUpperCase() || '—']]);
  refreshDelay = Math.max(3000, Math.min(30000, Number(service.dashboard_refresh_sec || 5) * 1000));
}
async function refresh() {
  if (!authenticated || refreshing) return;
  refreshing = true;
  try {
    await pollModelTasks();
    const [status, jobs] = await Promise.all([request('/api/status'), refreshJobs()]);
    renderOverview(status, jobs);
    if (location.hash === '#models') await refreshModels();
    $('last-updated').textContent = `最后同步 ${new Date().toLocaleTimeString('zh-CN')} · 每 ${refreshDelay / 1000} 秒刷新`;
    setConnection(true, '服务已连接');
  } catch (error) {
    setConnection(false, error.status === 401 ? '需要认证' : '同步失败');
    report(error);
  } finally { refreshing = false; }
}
async function route() {
  const requested = location.hash.slice(1) || 'overview';
  const page = pages.includes(requested) ? requested : 'overview';
  for (const name of pages) $(`page-${name}`).hidden = name !== page;
  document.querySelectorAll('nav a').forEach((link) => {
    if (link.hash === `#${page}`) link.setAttribute('aria-current', 'page');
    else link.removeAttribute('aria-current');
  });
  const titles = {overview:'概览',run:'运行',config:'配置',api:'API',models:'模型',jobs:'任务产物'};
  document.title = `${titles[page]} · CueLoom`;
  if (!authenticated) return;
  try {
    if (page === 'config') await loadConfig();
    if (page === 'api') await loadProfiles();
    if (page === 'models') { await loadConfig(); await refreshModels(true); }
    if (page === 'jobs' || page === 'run') await refresh();
  } catch (error) { report(error); }
}
function initTheme() {
  let value = 'system';
  try { value = localStorage.getItem('cueloom.theme') || 'system'; } catch { /* 无存储权限时跟随系统。 */ }
  if (!['system','light','dark'].includes(value)) value = 'system';
  $('theme').value = value;
  function apply(theme) {
    if (theme === 'system') delete document.documentElement.dataset.theme;
    else document.documentElement.dataset.theme = theme;
  }
  apply(value);
  $('theme').addEventListener('change', () => {
    apply($('theme').value);
    try { localStorage.setItem('cueloom.theme', $('theme').value); } catch { /* 主题仍在当前页面生效。 */ }
  });
}
function initApi() {
  const contracts = [['GET','/api/status','服务与脱敏配置摘要'],['GET / PUT','/api/config','动态 schema / 部分更新'],['POST','/api/uploads','原始 File；X-Filename 编码文件名'],['POST','/api/jobs','upload_id / target_lang / bilingual / formats / demo'],['GET','/api/jobs/{id}','阶段结果与任务状态'],['GET','/api/jobs/{id}/artifacts','字幕产物与鉴权下载'],['GET','/api/tasks/{id}','后台下载状态'],['GET','/api/models','模型资产清单']];
  for (const [method, path, description] of contracts) {
    const row = el('div'); row.append(el('span', method, 'badge'), el('code', path), el('span', description, 'muted')); $('api-contracts').append(row);
  }
  $('probe-button').addEventListener('click', () => action($('probe-button'), async () => {
    $('probe-result').textContent = '正在测试上游模型连接…';
    try {
      const result = await request('/api/llm/probe', {method:'POST'});
      const categories = {ok:'连接正常',upstream_error:'上游连接失败，请检查地址、密钥与模型配置',not_configured:'LLM 尚未配置完整'};
      $('probe-result').textContent = `${categories[result.category] || result.category} · ${result.latency_ms} ms · ${result.model || '未设置模型'}`;
      if (!result.ok) notice($('probe-result').textContent);
    } catch (error) { $('probe-result').textContent = error.message; throw error; }
  }));
}
initTheme(); initJobs(); initConfig(); initModels(); initApi();
$('notice-close').addEventListener('click', () => { $('notice').hidden = true; });
$('auth-open').addEventListener('click', () => openAuth());
$('api-login').addEventListener('click', () => openAuth());
$('auth-close').addEventListener('click', () => $('auth-dialog').close());
$('auth-form').addEventListener('submit', (event) => {
  event.preventDefault();
  if (authBusy) return;
  authBusy = true;
  action($('auth-form').querySelector('[type=submit]'), async () => {
    try {
      const value = $('auth-token').value.trim();
      if (!value && !lastAuth?.local) throw new Error('请输入访问 token。');
      setToken(value);
      $('auth-token').value = '';
      if (await authenticate()) {
        $('auth-dialog').close(); $('notice').hidden = true;
        await loadConfig(); await refresh(); await route();
      }
    } catch (error) { $('auth-error').textContent = error.message; }
    finally { authBusy = false; }
  });
});
$('auth-clear').addEventListener('click', () => action($('auth-clear'), async () => {
  setToken(''); $('auth-token').value = '';
  await authenticate();
  if (authenticated) { $('auth-dialog').close(); await refresh(); }
}));
window.addEventListener('cueloom:unauthorized', () => {
  authenticated = false;
  $('auth-state').textContent = '认证失效，请重新连接';
  setConnection(false, '需要认证');
  openAuth('认证失效或远端连接不安全。请输入有效 token，并确认使用 HTTPS。');
});
window.addEventListener('hashchange', route);
window.addEventListener('cueloom:config-updated', () => refresh());
async function start() {
  await route();
  try { if (await authenticate()) { await loadConfig(); await refresh(); await route(); } }
  catch (error) { setConnection(false, '连接失败'); report(error); }
  schedule();
}
function schedule() {
  setTimeout(async () => {
    if (!document.hidden) {
      if (!authenticated && !$('auth-dialog').open) {
        try { if (await authenticate()) { await loadConfig(); await refresh(); } } catch (error) { report(error); }
      } else await refresh();
    }
    schedule();
  }, refreshDelay);
}
start();
