let token = '';
try { token = sessionStorage.getItem('cueloom.web.token') || ''; } catch { /* 禁用存储时仍允许本机访问。 */ }
export function setToken(value) {
  if (value) sessionStorage.setItem('cueloom.web.token', value);
  else sessionStorage.removeItem('cueloom.web.token');
  token = value;
}
export function headers(method = 'GET') {
  const result = {};
  if (token) result.Authorization = `Bearer ${token}`;
  if (!['GET', 'HEAD', 'OPTIONS'].includes(method)) result['X-Cueloom-Client'] = 'web';
  return result;
}
export function responseError(status, data) {
  if (status === 401) window.dispatchEvent(new Event('cueloom:unauthorized'));
  const error = new Error(data?.error?.message || `请求失败（HTTP ${status}）`);
  error.status = status;
  error.code = data?.error?.code;
  if (data?.error?.hint) error.message += ` · ${data.error.hint}`;
  return error;
}
export async function request(path, {method = 'GET', body, blob = false} = {}) {
  const options = {method, credentials:'same-origin', cache:'no-store', headers:headers(method)};
  if (body !== undefined) {
    options.headers['Content-Type'] = 'application/json';
    options.body = JSON.stringify(body);
  }
  const response = await fetch(path, options);
  if (!response.ok) {
    const data = await response.json().catch(() => null);
    throw responseError(response.status, data);
  }
  return blob ? response.blob() : response.json();
}
export function upload(file, onProgress) {
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhr.open('POST', '/api/uploads');
    xhr.timeout = 30 * 60 * 1000;
    for (const [key, value] of Object.entries(headers('POST'))) xhr.setRequestHeader(key, value);
    xhr.setRequestHeader('X-Filename', encodeURIComponent(file.name));
    xhr.setRequestHeader('Content-Type', 'application/octet-stream');
    xhr.upload.onprogress = (event) => onProgress(event.loaded, event.lengthComputable ? event.total : null);
    xhr.onload = () => {
      let data;
      try { data = JSON.parse(xhr.responseText); } catch { reject(new Error('上传响应不是有效 JSON')); return; }
      if (xhr.status >= 200 && xhr.status < 300) resolve(data);
      else reject(responseError(xhr.status, data));
    };
    xhr.onerror = () => reject(new Error('上传连接失败，请检查网络后重新上传。'));
    xhr.ontimeout = () => reject(new Error('上传超时，请重新上传。'));
    xhr.onabort = () => reject(new Error('上传已取消。'));
    xhr.send(file);
  });
}
