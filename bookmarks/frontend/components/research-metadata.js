import { HeadlessElement } from "../utils/element.js";

class ResearchMetadata extends HeadlessElement {
  init() {
    this.form = this.closest("form");
    this.button = this.querySelector("button");
    this.status = this.querySelector('[role="status"]');
    this.url = this.form.elements.url;
    this.fields = [this.form.elements.title, this.form.elements.description];
    this.revisions = new Map(this.fields.map((field) => [field, 0]));
    this.onRead = () => this.read();
    this.onInput = (event) => {
      const field = event.target;
      this.revisions.set(field, this.revisions.get(field) + 1);
    };
    this.onURLInput = () => this.controller?.abort("url-change");
    this.onBeforeCache = () => {
      this.controller?.abort("navigation");
      this.button.disabled = false;
      this.status.textContent = "";
      this.removeAttribute("aria-busy");
    };
    this.button.addEventListener("click", this.onRead);
    this.url.addEventListener("input", this.onURLInput);
    this.fields.forEach((field) =>
      field.addEventListener("input", this.onInput),
    );
    document.addEventListener("turbo:before-cache", this.onBeforeCache);
    this.button.disabled = false;
  }

  disconnectedCallback() {
    this.controller?.abort("navigation");
    this.button?.removeEventListener("click", this.onRead);
    this.url?.removeEventListener("input", this.onURLInput);
    this.fields?.forEach((field) =>
      field.removeEventListener("input", this.onInput),
    );
    document.removeEventListener("turbo:before-cache", this.onBeforeCache);
    this.__initialized = false;
  }

  async read() {
    if (!this.url.value.trim() || !this.url.checkValidity()) {
      this.status.textContent = "请先填写有效的原始链接。";
      this.url.focus();
      return;
    }
    if (this.controller) return;
    const url = this.url.value.trim();
    const snapshot = this.fields.map((field) => ({
      field,
      value: field.value,
      revision: this.revisions.get(field),
    }));
    const controller = new AbortController();
    this.controller = controller;
    this.button.disabled = true;
    this.setAttribute("aria-busy", "true");
    this.status.textContent = "正在读取资料信息，你仍可以填写或保存资料…";
    const timer = setTimeout(() => controller.abort("timeout"), 15000);
    try {
      const response = await fetch(this.dataset.endpoint, {
        method: "POST",
        credentials: "same-origin",
        headers: { Accept: "application/json" },
        body: new URLSearchParams({
          url,
          csrfmiddlewaretoken: this.form.elements.csrfmiddlewaretoken.value,
        }),
        signal: controller.signal,
      });
      if (
        response.redirected ||
        !response.headers.get("Content-Type")?.includes("application/json")
      ) {
        this.status.textContent =
          "读取未完成，请确认登录状态；已有内容已保留。";
        return;
      }
      const result = await response.json();
      if (!this.isConnected || this.url.value.trim() !== url) return;
      if (!response.ok || !result.available) {
        this.status.textContent =
          result.message || "未能读取资料信息，你仍可以手动填写并保存。";
        return;
      }
      let filled = 0;
      for (const { field, value, revision } of snapshot) {
        // Protect existing text and edits made while the request was running.
        if (
          !value.trim() &&
          field.value === value &&
          this.revisions.get(field) === revision &&
          result[field.name]
        ) {
          field.value = result[field.name];
          filled += 1;
        }
      }
      this.status.textContent = filled
        ? "已补全空白标题或简介，请确认后保存。已有内容已保留。"
        : "已读取，现有标题和简介已保留；如需重新填入，可清空相应字段后再读取。";
    } catch {
      if (!this.isConnected || controller.signal.reason === "navigation")
        return;
      this.status.textContent =
        controller.signal.reason === "url-change"
          ? "链接已更改，请重新读取资料信息。"
          : "读取失败或超时，你仍可以手动填写并保存。";
    } finally {
      clearTimeout(timer);
      if (this.controller === controller) {
        this.controller = null;
        this.button.disabled = false;
        this.removeAttribute("aria-busy");
      }
    }
  }
}

customElements.define("yuanjian-metadata", ResearchMetadata);
