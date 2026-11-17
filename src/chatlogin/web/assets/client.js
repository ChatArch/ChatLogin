export class ChatLoginProtocolError extends Error {
    constructor() { super('Invalid or unsupported ChatLogin response'); this.name = 'ChatLoginProtocolError'; }
}
export class ChatLoginHTTPError extends Error {
    constructor(status) {
        super(`ChatLogin request failed (HTTP ${status})`);
        this.name = 'ChatLoginHTTPError';
        this.status = status;
    }
}
export class ChatLoginNetworkError extends Error {
    constructor() { super('ChatLogin request failed or timed out'); this.name = 'ChatLoginNetworkError'; }
}
function object(value) {
    if (value === null || typeof value !== 'object' || Array.isArray(value))
        throw new ChatLoginProtocolError();
    return value;
}
function principal(value) {
    const user = object(value);
    if (typeof user.user_id !== 'string' || !user.user_id || user.user_id.length > 256 ||
        typeof user.display_name !== 'string' || user.display_name.length > 256 ||
        !['user', 'admin', 'owner'].includes(user.role))
        throw new ChatLoginProtocolError();
    return { user_id: user.user_id, display_name: user.display_name, role: user.role };
}
function csrf(value) {
    if (typeof value !== 'string' || !/^[\x21-\x7e]{1,1024}$/.test(value))
        throw new ChatLoginProtocolError();
    return value;
}
function session(value) {
    const data = object(value);
    if (data.authenticated === false && data.user === null && data.csrf_token === null) {
        return { authenticated: false, user: null, csrf_token: null };
    }
    if (data.authenticated === true)
        return { authenticated: true, user: principal(data.user), csrf_token: csrf(data.csrf_token) };
    throw new ChatLoginProtocolError();
}
function routePath(value, template = false) {
    if (typeof value !== 'string' || !value.startsWith('/') || value.startsWith('//') ||
        !(template ? /^\/[A-Za-z0-9._~/{\}-]*$/ : /^\/[A-Za-z0-9._~/-]*$/).test(value) ||
        value.includes('//') || value.split('/').some(part => part === '.' || part === '..')) {
        throw new ChatLoginProtocolError();
    }
    return value;
}
/** Match the server's conservative local-next rule; never navigate automatically. */
export function safeNext(value) {
    if (typeof value !== 'string' || value.length > 4096 || Array.from(value).length > 2048)
        return '/';
    let decoded = value;
    for (let i = 0; i < 5; i++) {
        if (!decoded.startsWith('/') || decoded.startsWith('//') || /[\\\x00-\x20\x7f]/.test(decoded))
            return '/';
        // Match urllib.parse.unquote, including malformed '%' and invalid UTF-8.
        const next = decoded.replace(/(?:%[0-9a-f]{2})+/gi, chunk => new TextDecoder().decode(Uint8Array.from(chunk.match(/%[0-9a-f]{2}/gi) ?? [], byte => parseInt(byte.slice(1), 16))));
        if (next === decoded)
            return value;
        decoded = next;
    }
    return '/';
}
function discovery(value) {
    const data = object(value), capabilities = object(data.capabilities), pages = object(data.pages);
    if (data.schema_version !== 1 || typeof data.version !== 'string' || !Array.isArray(data.operations) ||
        !['login', 'managed_users', 'profile'].every(key => typeof capabilities[key] === 'boolean')) {
        throw new ChatLoginProtocolError();
    }
    const operations = data.operations.map(item => {
        const operation = object(item);
        if (typeof operation.method !== 'string' || !/^[A-Z]+$/.test(operation.method))
            throw new ChatLoginProtocolError();
        return { method: operation.method, path: routePath(operation.path, true) };
    });
    const localPages = {};
    for (const key of ['login', 'profile', 'users']) {
        if (pages[key] !== undefined)
            localPages[key] = routePath(pages[key]);
    }
    return { version: data.version, schema_version: 1, operations, pages: localPages,
        capabilities: { login: capabilities.login, managed_users: capabilities.managed_users,
            profile: capabilities.profile } };
}
export function publicSession(value) {
    return value.authenticated ? { authenticated: true, user: value.user } : { authenticated: false, user: null };
}
/** Presentation hints only: every operation still needs server authorization. */
export function accountLinks(manifest, current) {
    const links = [];
    const add = (key) => {
        const url = manifest.pages[key];
        if (url !== undefined)
            links.push({ key, url: routePath(url) });
    };
    if (!current.authenticated) {
        if (manifest.capabilities.login)
            add('login');
        return links;
    }
    if (manifest.capabilities.profile)
        add('profile');
    if (manifest.capabilities.managed_users && ['admin', 'owner'].includes(current.user.role))
        add('users');
    return links;
}
export class ChatLoginClient {
    constructor(options = {}) {
        this.mutationTail = Promise.resolve();
        const browserOrigin = typeof location === 'undefined' ? undefined : location.origin;
        const origin = options.origin ?? browserOrigin;
        if (!origin || browserOrigin && origin !== browserOrigin)
            throw new TypeError('Use the current browser origin');
        let parsed;
        try {
            parsed = new URL(origin);
        }
        catch {
            throw new TypeError('A concrete HTTP(S) origin is required');
        }
        if (!['http:', 'https:'].includes(parsed.protocol) || parsed.origin !== origin || parsed.username || parsed.password) {
            throw new TypeError('A canonical HTTP(S) origin is required');
        }
        this.origin = parsed.origin;
        const basePath = options.basePath ?? '/auth';
        this.basePath = basePath === '' ? '' : routePath(basePath).replace(/\/$/, '');
        const fetcher = options.fetch ?? globalThis.fetch;
        if (typeof fetcher !== 'function')
            throw new TypeError('A browser fetch implementation is required');
        this.fetcher = fetcher.bind(globalThis);
        this.timeoutMs = options.timeoutMs ?? 15000;
        if (!Number.isFinite(this.timeoutMs) || this.timeoutMs <= 0 || this.timeoutMs > 120000)
            throw new TypeError('Invalid timeout');
    }
    url(path) {
        if (typeof path !== 'string' || safeNext(path) !== path)
            throw new TypeError('Use a safe same-origin absolute path');
        const url = new URL(path, this.origin);
        if (url.origin !== this.origin)
            throw new TypeError('Cross-origin requests are not supported');
        return url.href;
    }
    async operation(signal, callback) {
        const controller = new AbortController();
        const abort = () => controller.abort();
        if (signal?.aborted)
            controller.abort();
        signal?.addEventListener('abort', abort, { once: true });
        const timer = setTimeout(abort, this.timeoutMs);
        try {
            if (controller.signal.aborted)
                throw new ChatLoginNetworkError();
            return await callback(controller.signal);
        }
        finally {
            clearTimeout(timer);
            signal?.removeEventListener('abort', abort);
        }
    }
    async send(path, init, signal, checkHTTP = true) {
        const url = this.url(path);
        const headers = new Headers(init.headers);
        for (const key of ['authorization', 'cookie', 'origin', 'host', 'x-chatlogin-client']) {
            if (headers.has(key))
                throw new TypeError('Authentication transport headers are browser managed');
        }
        let response;
        try {
            response = await this.fetcher(url, { ...init, headers, signal, credentials: 'same-origin',
                mode: 'same-origin', cache: 'no-store', redirect: 'error' });
        }
        catch {
            throw new ChatLoginNetworkError();
        }
        if (signal.aborted)
            throw new ChatLoginNetworkError();
        if (response.url && new URL(response.url).origin !== this.origin)
            throw new ChatLoginProtocolError();
        if (checkHTTP && !response.ok)
            throw new ChatLoginHTTPError(response.status);
        return response;
    }
    async json(response) {
        if (!/^application\/(?:json|[a-z0-9.+-]+\+json)(?:;|$)/i.test(response.headers.get('Content-Type') ?? '')) {
            throw new ChatLoginProtocolError();
        }
        let text;
        try {
            text = await response.text();
        }
        catch {
            throw new ChatLoginNetworkError();
        }
        if (text.length > 65536)
            throw new ChatLoginProtocolError();
        try {
            return JSON.parse(text);
        }
        catch {
            throw new ChatLoginProtocolError();
        }
    }
    async readSession(signal) {
        return session(await this.json(await this.send(this.basePath + '/session', {}, signal)));
    }
    mutation(signal, callback) {
        // A late login must not restore a cookie after a reported successful logout.
        const task = this.mutationTail.then(() => this.operation(signal, callback));
        this.mutationTail = task.then(() => undefined, () => undefined);
        return task;
    }
    discover(options = {}) {
        return this.operation(options.signal, async (signal) => discovery(await this.json(await this.send(this.basePath + '/api', {}, signal))));
    }
    session(options = {}) {
        return this.operation(options.signal, signal => this.readSession(signal));
    }
    login(input, options = {}) {
        if (typeof input.username !== 'string' || typeof input.password !== 'string' || !input.username || !input.password) {
            return Promise.reject(new TypeError('Username and password are required'));
        }
        const payload = { username: input.username, password: input.password, next: safeNext(input.next) };
        // Do not merge a later logout with a logout that precedes this login.
        this.logoutTask = undefined;
        return this.mutation(options.signal, async (signal) => {
            const current = await this.readSession(signal);
            const headers = { 'Content-Type': 'application/json' };
            if (current.authenticated)
                headers['X-CSRF-Token'] = current.csrf_token;
            const result = object(await this.json(await this.send(this.basePath + '/login', { method: 'POST', headers,
                body: JSON.stringify(payload) }, signal)));
            if (result.authenticated !== true || typeof result.next !== 'string')
                throw new ChatLoginProtocolError();
            return { authenticated: true, user: principal(result.user), csrf_token: csrf(result.csrf_token), next: safeNext(result.next) };
        });
    }
    logout(options = {}) {
        // Concurrent callers share one request; the first caller owns cancellation.
        if (this.logoutTask)
            return this.logoutTask;
        const task = this.mutation(options.signal, async (signal) => {
            const current = await this.readSession(signal);
            if (!current.authenticated)
                return { authenticated: false };
            const result = object(await this.json(await this.send(this.basePath + '/logout', { method: 'POST',
                headers: { 'X-CSRF-Token': current.csrf_token } }, signal)));
            if (result.authenticated !== false)
                throw new ChatLoginProtocolError();
            return { authenticated: false };
        }).finally(() => { if (this.logoutTask === task)
            this.logoutTask = undefined; });
        this.logoutTask = task;
        return task;
    }
    /** Send an application request, attaching fresh CSRF for every unsafe method.
     * Returns the business Response, including non-2xx statuses. Does not retry
     * writes: the host owns errors, idempotency and session-change recovery.
     */
    request(path, init = {}) {
        // Validate before even querying the session or exposing its CSRF value.
        this.url(path);
        const method = (init.method ?? 'GET').toUpperCase();
        if (!['GET', 'HEAD', 'OPTIONS', 'POST', 'PUT', 'PATCH', 'DELETE'].includes(method)) {
            return Promise.reject(new TypeError('Unsupported browser method'));
        }
        return this.operation(init.signal ?? undefined, async (signal) => {
            const headers = new Headers(init.headers);
            headers.delete('X-CSRF-Token');
            if (!['GET', 'HEAD', 'OPTIONS'].includes(method)) {
                const current = await this.readSession(signal);
                if (!current.authenticated)
                    throw new ChatLoginHTTPError(401);
                headers.set('X-CSRF-Token', current.csrf_token);
            }
            return this.send(path, { ...init, method, headers }, signal, false);
        });
    }
}
export function createChatLoginClient(options = {}) {
    return new ChatLoginClient(options);
}
