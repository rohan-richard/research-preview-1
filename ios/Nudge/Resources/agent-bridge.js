(() => {
  if (window.agentBridge) return;

  const REF = 'data-agent-ref';
  const OVERLAY = 'data-agent-overlay';
  const MAX_ELEMENTS = 150;
  const MAX_TEXT = 6000;
  const INTERACTIVE =
    'a[href],button,input,select,textarea,[role="button"],[role="link"],[role="tab"],' +
    '[role="option"],[role="checkbox"],[role="radio"],[role="menuitem"],[tabindex]';
  const BLOCK_DISPLAY = new Set(['block', 'flex', 'grid', 'list-item', 'table', 'table-row', 'flow-root', 'table-cell']);

  const clean = (s) => (s || '').replace(/\s+/g, ' ').trim();

  function isVisible(el) {
    if (el.closest('[aria-hidden="true"]') || el.hasAttribute(OVERLAY)) return false;
    const style = getComputedStyle(el);
    if (style.display === 'none' || style.visibility === 'hidden' || style.opacity === '0') return false;
    const r = el.getBoundingClientRect();
    return r.width > 0 && r.height > 0;
  }

  function inViewport(el) {
    const r = el.getBoundingClientRect();
    return r.bottom > 0 && r.right > 0 && r.top < innerHeight && r.left < innerWidth;
  }

  function accName(el) {
    const aria = el.getAttribute('aria-label');
    if (aria) return clean(aria);
    const labelledBy = el.getAttribute('aria-labelledby');
    if (labelledBy) {
      const parts = labelledBy.split(/\s+/).map((id) => document.getElementById(id)).filter(Boolean);
      if (parts.length) return clean(parts.map((p) => p.innerText).join(' '));
    }
    if (el.id) {
      const label = document.querySelector(`label[for="${CSS.escape(el.id)}"]`);
      if (label) return clean(label.innerText);
    }
    const wrapping = el.closest('label');
    if (wrapping && el.tagName !== 'LABEL') return clean(wrapping.innerText);
    const text = clean(el.innerText);
    if (text) return text;
    if (el.tagName === 'INPUT' && ['submit', 'button', 'reset'].includes(el.type) && el.value) return clean(el.value);
    const img = el.querySelector('img[alt]');
    if (img) return clean(img.alt);
    return clean(el.getAttribute('placeholder') || el.getAttribute('title') || el.getAttribute('alt'));
  }

  function roleOf(el) {
    const explicit = el.getAttribute('role');
    if (explicit) return explicit;
    switch (el.tagName) {
      case 'A': return 'link';
      case 'BUTTON': return 'button';
      case 'SELECT': return 'combobox';
      case 'TEXTAREA': return 'textbox';
      case 'INPUT':
        if (el.type === 'checkbox' || el.type === 'radio') return el.type;
        if (['submit', 'button', 'reset'].includes(el.type)) return 'button';
        return 'textbox';
      default: return 'generic';
    }
  }

  function describe(el, ref) {
    const d = { ref, role: roleOf(el), name: accName(el), tag: el.tagName.toLowerCase(), inViewport: inViewport(el) };
    if (el.tagName === 'INPUT') d.type = el.type;
    if (el.tagName === 'BUTTON') d.type = el.form ? el.type : 'button';
    if (el.disabled || el.getAttribute('aria-disabled') === 'true') d.disabled = true;
    if (el.tagName === 'INPUT' && (el.type === 'checkbox' || el.type === 'radio')) d.checked = el.checked;
    const pressed = el.getAttribute('aria-pressed');
    if (pressed !== null) d.pressed = pressed === 'true';
    const selected = el.getAttribute('aria-selected');
    if (selected !== null) d.selected = selected === 'true';
    if (el.getAttribute('aria-current')) d.selected = true;
    if (el.tagName === 'SELECT') {
      d.options = Array.from(el.options).map((o) => clean(o.text));
      d.value = el.selectedIndex >= 0 ? clean(el.options[el.selectedIndex].text) : '';
    } else if ((el.tagName === 'INPUT' && el.type !== 'password' && d.role === 'textbox') || el.tagName === 'TEXTAREA') {
      d.value = el.value;
    }
    if (el.tagName === 'A') d.href = el.getAttribute('href');
    const context = cardContext(el, d.name);
    if (context) d.context = context;
    return d;
  }

  // Lines of the small enclosing card/row, minus its own controls, so two "Cancel"
  // links can be told apart and the approval sheet can show the right visit.
  function cardContext(el, name) {
    const card = el.parentElement && el.parentElement.closest('article, li, tr, section, [class*="card"]');
    if (!card || card === document.body) return '';
    const controls = Array.from(card.querySelectorAll(INTERACTIVE));
    if (controls.length > 12) return '';
    const controlNames = new Set(controls.map(accName).filter(Boolean));
    controlNames.add(name);
    const lines = outlineText(card).split('\n')
      .map((ln) => ln.replace(/^#+\s*/, '').trim())
      .filter((ln) => ln && !controlNames.has(ln));
    const text = lines.join('\n');
    if (!text || text.length > 400) return '';
    return text.slice(0, 200);
  }

  function collectElements() {
    document.querySelectorAll(`[${REF}]`).forEach((el) => el.removeAttribute(REF));
    let nodes = Array.from(document.querySelectorAll(INTERACTIVE)).filter(isVisible);
    if (nodes.length > MAX_ELEMENTS) {
      const visible = nodes.filter(inViewport);
      const rest = nodes.filter((n) => !inViewport(n));
      nodes = visible.concat(rest).slice(0, MAX_ELEMENTS);
      nodes.sort((a, b) => (a.compareDocumentPosition(b) & Node.DOCUMENT_POSITION_FOLLOWING ? -1 : 1));
    }
    return nodes.map((el, i) => {
      el.setAttribute(REF, String(i + 1));
      return describe(el, i + 1);
    });
  }

  function outlineText(root) {
    const lines = [];
    let cur = [];
    const flush = () => {
      const line = clean(cur.join(' ')).replace(/\s+([,.;:!?])/g, '$1');
      if (line) lines.push(line);
      cur = [];
    };
    const walk = (node) => {
      if (node.nodeType === Node.TEXT_NODE) {
        const t = clean(node.textContent);
        if (t) cur.push(t);
        return;
      }
      if (node.nodeType !== Node.ELEMENT_NODE) return;
      const el = node;
      if (['SCRIPT', 'STYLE', 'NOSCRIPT', 'TEMPLATE', 'SVG'].includes(el.tagName)) return;
      if (!isVisible(el)) return;
      const heading = /^H[1-6]$/.test(el.tagName);
      const block = heading || BLOCK_DISPLAY.has(getComputedStyle(el).display);
      if (block) flush();
      if (heading) {
        lines.push((el.tagName === 'H1' ? '# ' : '## ') + clean(el.innerText));
        return;
      }
      if (el.tagName === 'SELECT') {
        cur.push(`[${clean(el.options[el.selectedIndex]?.text || '')}]`);
        return;
      }
      if (el.tagName === 'INPUT' || el.tagName === 'TEXTAREA') {
        if (el.type !== 'password' && el.value) cur.push(`[${clean(el.value)}]`);
        return;
      }
      el.childNodes.forEach(walk);
      if (block) flush();
    };
    walk(root);
    flush();
    return lines.join('\n');
  }

  function findRef(ref) {
    const el = document.querySelector(`[${REF}="${ref}"]`);
    if (!el || !el.isConnected) throw new Error(`stale ref ${ref}: element no longer exists; take a new observation`);
    return el;
  }

  const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

  let actionEpoch = 0;
  function stop() { actionEpoch++; }
  async function snapshot() {
    if (document.querySelector('input[type="password"]') || /\/portal\/(login|forgot)/.test(location.pathname)) {
      return { url: location.pathname, title: 'Sign in', viewport: { width: innerWidth, height: innerHeight }, scroll: { x: 0, y: 0 }, pageHeight: 0, elements: [], text: 'Patient sign-in required.', dialogs: [] };
    }
    const dialogs = Array.from(document.querySelectorAll('[role="dialog"],[role="alertdialog"],dialog[open]'))
      .filter(isVisible)
      .map((d) => clean(d.innerText).slice(0, 1000));
    return {
      url: location.pathname + location.search,
      title: document.title,
      viewport: { width: innerWidth, height: innerHeight },
      scroll: { x: Math.round(scrollX), y: Math.round(scrollY) },
      pageHeight: document.documentElement.scrollHeight,
      elements: collectElements(),
      text: outlineText(document.body).slice(0, MAX_TEXT),
      dialogs,
    };
  }

  async function highlight(ref, ms = 400) {
    const el = findRef(ref);
    el.scrollIntoView({ block: 'center', inline: 'nearest' });
    const r = el.getBoundingClientRect();
    const box = document.createElement('div');
    box.setAttribute(OVERLAY, '1');
    Object.assign(box.style, {
      position: 'fixed',
      left: `${r.left - 3}px`,
      top: `${r.top - 3}px`,
      width: `${r.width + 6}px`,
      height: `${r.height + 6}px`,
      border: '3px solid #ff7a00',
      borderRadius: '8px',
      boxShadow: '0 0 0 4px rgba(255,122,0,0.25)',
      pointerEvents: 'none',
      zIndex: '2147483647',
      transition: 'opacity 150ms',
    });
    document.body.appendChild(box);
    await sleep(ms);
    box.remove();
    return { ok: true };
  }

  async function click(ref, expected) {
    const epoch = actionEpoch;
    const el = findRef(ref);
    if (el.disabled) throw new Error(`element ${ref} is disabled`);
    await highlight(ref);
    if (epoch !== actionEpoch) throw new Error('Stopped by patient');
    if (expected && (expected.url !== location.pathname + location.search || expected.text !== outlineText(document.body).slice(0, MAX_TEXT) || expected.name !== accName(el))) throw new Error('Page changed after approval; not submitted');
    if (expected?.fields?.some(field => {
      const current = findRef(field.ref);
      const value = current.tagName === 'SELECT' ? clean(current.options[current.selectedIndex]?.text || '') : (current.type === 'checkbox' || current.type === 'radio') ? '' : (current.value || '');
      return value !== field.value || !!current.checked !== field.checked;
    })) throw new Error('Form changed after approval; not submitted');
    const r = el.getBoundingClientRect();
    const init = { bubbles: true, cancelable: true, clientX: r.left + r.width / 2, clientY: r.top + r.height / 2, button: 0 };
    el.dispatchEvent(new PointerEvent('pointerdown', init));
    el.dispatchEvent(new MouseEvent('mousedown', init));
    el.focus?.();
    el.dispatchEvent(new PointerEvent('pointerup', init));
    el.dispatchEvent(new MouseEvent('mouseup', init));
    el.click();
    return { ok: true, name: accName(el) };
  }

  function setNativeValue(el, value) {
    const proto = el.tagName === 'TEXTAREA' ? HTMLTextAreaElement.prototype
      : el.tagName === 'SELECT' ? HTMLSelectElement.prototype : HTMLInputElement.prototype;
    Object.getOwnPropertyDescriptor(proto, 'value').set.call(el, value);
  }

  async function typeText(ref, text, clear = true) {
    const epoch = actionEpoch;
    const el = findRef(ref);
    if (el.tagName === 'INPUT' && (el.type === 'password' || /username|password|access code/i.test(accName(el)))) {
      throw new Error('refused: the assistant never types into password fields; ask the patient to sign in');
    }
    if (!['INPUT', 'TEXTAREA'].includes(el.tagName) && !el.isContentEditable) {
      throw new Error(`element ${ref} is not a text field`);
    }
    await highlight(ref);
    if (epoch !== actionEpoch) throw new Error('Stopped by patient');
    el.focus();
    if (el.isContentEditable) {
      el.textContent = clear ? text : el.textContent + text;
    } else {
      setNativeValue(el, clear ? text : el.value + text);
    }
    el.dispatchEvent(new Event('input', { bubbles: true }));
    el.dispatchEvent(new Event('change', { bubbles: true }));
    return { ok: true, value: el.isContentEditable ? el.textContent : el.value };
  }

  async function selectOption(ref, option) {
    const epoch = actionEpoch;
    const el = findRef(ref);
    if (el.tagName !== 'SELECT') throw new Error(`element ${ref} is not a select`);
    const want = clean(String(option)).toLowerCase();
    const match = Array.from(el.options).find((o) => clean(o.text).toLowerCase() === want)
      || Array.from(el.options).find((o) => o.value.toLowerCase() === want)
      || Array.from(el.options).find((o) => clean(o.text).toLowerCase().includes(want));
    if (!match) {
      throw new Error(`no option "${option}"; options are: ${Array.from(el.options).map((o) => clean(o.text)).join(' | ')}`);
    }
    await highlight(ref);
    if (epoch !== actionEpoch) throw new Error('Stopped by patient');
    el.focus();
    setNativeValue(el, match.value);
    el.dispatchEvent(new Event('input', { bubbles: true }));
    el.dispatchEvent(new Event('change', { bubbles: true }));
    return { ok: true, value: clean(match.text) };
  }

  async function scroll(arg) {
    if (arg && arg.ref != null) {
      findRef(arg.ref).scrollIntoView({ block: 'center', behavior: 'instant' });
    } else {
      const dir = (arg && arg.direction) || 'down';
      window.scrollBy({ top: (dir === 'up' ? -0.8 : 0.8) * innerHeight, behavior: 'instant' });
    }
    await sleep(50);
    return { ok: true, scroll: { x: Math.round(scrollX), y: Math.round(scrollY) }, pageHeight: document.documentElement.scrollHeight };
  }

  function isOurs(node) {
    return node && node.nodeType === Node.ELEMENT_NODE && node.hasAttribute(OVERLAY);
  }

  async function waitForSettle(opts) {
    const quietMs = (opts && opts.quietMs) || 500;
    const timeoutMs = (opts && opts.timeoutMs) || 5000;
    const start = Date.now();
    return new Promise((resolve) => {
      let quietTimer = null;
      let observer = null;
      const finish = (reason) => {
        clearTimeout(quietTimer);
        observer?.disconnect();
        resolve({ ok: true, reason, waitedMs: Date.now() - start });
      };
      const arm = () => {
        clearTimeout(quietTimer);
        quietTimer = setTimeout(() => {
          if (document.readyState === 'complete') finish('quiet');
          else arm();
        }, quietMs);
      };
      observer = new MutationObserver((records) => {
        const real = records.some((r) => !isOurs(r.target)
          && !Array.from(r.addedNodes).every(isOurs)
          && !Array.from(r.removedNodes).every(isOurs)
          && r.attributeName !== REF);
        if (real) arm();
      });
      observer.observe(document.documentElement, { subtree: true, childList: true, attributes: true, characterData: true });
      setTimeout(() => finish('timeout'), timeoutMs);
      arm();
    });
  }

  window.agentBridge = { snapshot, click, typeText, selectOption, scroll, waitForSettle, highlight, stop };
})();
