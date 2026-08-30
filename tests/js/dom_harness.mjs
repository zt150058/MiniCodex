export class TestTextNode {
  constructor(text) {
    this.nodeType = 3;
    this.parentNode = null;
    this.data = String(text);
  }

  get textContent() {
    return this.data;
  }

  set textContent(value) {
    this.data = String(value);
  }

  remove() {
    if (this.parentNode) {
      this.parentNode._removeChild(this);
    }
  }
}


class TestClassList {
  constructor(element) {
    this.element = element;
  }

  add(...names) {
    const values = new Set(this.element.className.split(/\s+/).filter(Boolean));
    for (const name of names) values.add(name);
    this.element.className = [...values].join(" ");
  }

  remove(...names) {
    const rejected = new Set(names);
    this.element.className = this.element.className
      .split(/\s+/)
      .filter((name) => name && !rejected.has(name))
      .join(" ");
  }

  contains(name) {
    return this.element.className.split(/\s+/).includes(name);
  }

  toggle(name, force) {
    const enabled = force === undefined ? !this.contains(name) : Boolean(force);
    if (enabled) this.add(name);
    else this.remove(name);
    return enabled;
  }
}


export class TestElement {
  constructor(tagName) {
    this.nodeType = 1;
    this.tagName = String(tagName).toUpperCase();
    this.parentNode = null;
    this.childNodes = [];
    this.attributes = new Map();
    this.listeners = new Map();
    this.className = "";
    this.classList = new TestClassList(this);
    this.dataset = {};
    this.disabled = false;
    this.value = "";
    this.checked = false;
  }

  append(...nodes) {
    for (const node of nodes) {
      const child = typeof node === "string" ? new TestTextNode(node) : node;
      child.parentNode = this;
      this.childNodes.push(child);
    }
  }

  replaceChildren(...nodes) {
    for (const child of this.childNodes) child.parentNode = null;
    this.childNodes = [];
    this.append(...nodes);
  }

  _removeChild(node) {
    this.childNodes = this.childNodes.filter((child) => child !== node);
    node.parentNode = null;
  }

  remove() {
    if (this.parentNode) this.parentNode._removeChild(this);
  }

  setAttribute(name, value) {
    const rendered = String(value);
    this.attributes.set(name, rendered);
    if (name === "class") this.className = rendered;
    if (name === "id") this.id = rendered;
  }

  getAttribute(name) {
    if (name === "class") return this.className || null;
    return this.attributes.get(name) ?? null;
  }

  addEventListener(type, listener) {
    const listeners = this.listeners.get(type) ?? [];
    listeners.push(listener);
    this.listeners.set(type, listeners);
  }

  dispatchEvent(event) {
    event.target ??= this;
    event.currentTarget = this;
    for (const listener of this.listeners.get(event.type) ?? []) {
      listener.call(this, event);
    }
    return !event.defaultPrevented;
  }

  get textContent() {
    return this.childNodes.map((child) => child.textContent).join("");
  }

  set textContent(value) {
    this.replaceChildren(new TestTextNode(value));
  }
}


export class TestDocument {
  constructor() {
    this.body = new TestElement("body");
    this.listeners = new Map();
    this.visibilityState = "visible";
  }

  createElement(tagName) {
    return new TestElement(tagName);
  }

  createTextNode(text) {
    return new TestTextNode(text);
  }

  getElementById(id) {
    return findById(this.body, id);
  }

  addEventListener(type, listener) {
    const listeners = this.listeners.get(type) ?? [];
    listeners.push(listener);
    this.listeners.set(type, listeners);
  }

  dispatchEvent(event) {
    event.target ??= this;
    for (const listener of this.listeners.get(event.type) ?? []) {
      listener.call(this, event);
    }
    return true;
  }
}


function findById(node, id) {
  if (node.nodeType === 1 && node.getAttribute("id") === id) return node;
  for (const child of node.childNodes ?? []) {
    const match = findById(child, id);
    if (match) return match;
  }
  return null;
}


export function findElements(root, tagName) {
  const expected = String(tagName).toUpperCase();
  const matches = [];
  function visit(node) {
    if (node.nodeType === 1 && node.tagName === expected) matches.push(node);
    for (const child of node.childNodes ?? []) visit(child);
  }
  visit(root);
  return matches;
}
