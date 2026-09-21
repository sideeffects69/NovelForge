/*
 * The whole site's script. It only ENHANCES: every page is complete without it,
 * and if any part fails the page simply stays as the server sent it.
 *
 *   1. Search. The header link "Search" becomes a real box. The index
 *      (search-index.json) is fetched the first time the box is focused, so a
 *      visitor who never searches never downloads it. Every word must match
 *      somewhere (AND); titles count most, then headings, then the description,
 *      then the text. Up/Down and Enter choose, Esc closes, "/" or Ctrl+K focuses.
 *   2. Scroll-spy for the "On this page" list.
 *   3. Copy buttons on code blocks, and "#" links on headings.
 *
 * No framework, no third-party requests, no cookies, no storage.
 */
(function () {
  "use strict";

  var script = document.currentScript;
  var base = script ? script.src.replace(/[^\/]*$/, "") : "/";
  var $ = function (selector, scope) { return (scope || document).querySelector(selector); };
  var $$ = function (selector, scope) { return Array.prototype.slice.call((scope || document).querySelectorAll(selector)); };
  var attempt = function (fn) { try { fn(); } catch (error) { /* an enhancement must never break a page */ } };

  /* ---- 1. search ---- */

  function score(page, terms) {
    var title = page.t.toLowerCase();
    var headings = page.h.join(" ").toLowerCase();
    var about = (page.d + " " + page.g).toLowerCase();
    var text = page.b.toLowerCase();
    var total = 0;
    for (var i = 0; i < terms.length; i++) {
      var word = terms[i], points = 0, at = title.indexOf(word);
      if (at > -1) points += at === 0 || title.charAt(at - 1) === " " ? 12 : 8;
      if (headings.indexOf(word) > -1) points += 5;
      if (about.indexOf(word) > -1) points += 3;
      if (text.indexOf(word) > -1) points += 1;
      if (!points) return 0;
      total += points;
    }
    return total;
  }

  function initSearch() {
    var holder = $(".search");
    if (!holder) return;
    var pages = null, loading = false, shown = [], active = -1;

    var input = document.createElement("input");
    input.type = "search";
    input.placeholder = "Search";
    input.autocomplete = "off";
    input.spellcheck = false;
    input.setAttribute("aria-label", "Search NovelForge");
    input.setAttribute("role", "combobox");
    input.setAttribute("aria-expanded", "false");
    input.setAttribute("aria-controls", "search-results");
    var list = document.createElement("ul");
    list.id = "search-results";
    list.setAttribute("role", "listbox");
    list.hidden = true;
    holder.innerHTML = '<svg class="icon" aria-hidden="true" focusable="false"><use href="#i-search"/></svg>';
    holder.appendChild(input);
    holder.appendChild(list);
    holder.className += " live";

    function close() {
      list.hidden = true;
      input.setAttribute("aria-expanded", "false");
      active = -1;
    }

    function mark(index) {
      active = index;
      $$("li", list).forEach(function (item, i) {
        item.setAttribute("aria-selected", i === index ? "true" : "false");
      });
    }

    function render() {
      var terms = input.value.toLowerCase().split(/\s+/).filter(Boolean);
      list.innerHTML = "";
      if (!pages || !terms.length) return close();
      shown = pages.map(function (page) { return { page: page, points: score(page, terms) }; })
        .filter(function (hit) { return hit.points; })
        .sort(function (a, b) { return b.points - a.points; })
        .slice(0, 8);
      shown.forEach(function (hit) {
        var item = document.createElement("li");
        var link = document.createElement("a");
        var name = document.createElement("strong");
        var note = document.createElement("span");
        item.setAttribute("role", "option");
        link.href = base + hit.page.u;
        name.textContent = hit.page.t;
        note.textContent = hit.page.g;
        link.appendChild(name);
        link.appendChild(note);
        item.appendChild(link);
        list.appendChild(item);
      });
      if (!shown.length) {
        var none = document.createElement("li");
        none.className = "none";
        none.textContent = "Nothing found. Try fewer or different words.";
        list.appendChild(none);
      }
      list.hidden = false;
      input.setAttribute("aria-expanded", "true");
      mark(shown.length ? 0 : -1);
    }

    function load() {
      if (pages || loading) return;
      loading = true;
      fetch(base + "search-index.json").then(function (r) { return r.json(); })
        .then(function (data) { pages = data; render(); })
        .catch(function () { loading = false; });
    }

    input.addEventListener("focus", load);
    input.addEventListener("input", function () { load(); render(); });
    input.addEventListener("keydown", function (event) {
      if (event.key === "ArrowDown" || event.key === "ArrowUp") {
        if (!shown.length) return;
        event.preventDefault();
        mark((active + (event.key === "ArrowDown" ? 1 : -1) + shown.length) % shown.length);
      } else if (event.key === "Enter" && shown[active]) {
        event.preventDefault();
        window.location.href = base + shown[active].page.u;
      } else if (event.key === "Escape") {
        if (input.value) input.value = ""; else input.blur();
        close();
      }
    });
    document.addEventListener("click", function (event) {
      if (!holder.contains(event.target)) close();
    });
    document.addEventListener("keydown", function (event) {
      var typing = /^(INPUT|TEXTAREA|SELECT)$/.test(event.target.tagName) || event.target.isContentEditable;
      var slash = event.key === "/" && !typing && !event.ctrlKey && !event.metaKey && !event.altKey;
      var ctrlK = event.key.toLowerCase() === "k" && (event.ctrlKey || event.metaKey);
      if (slash || ctrlK) {
        event.preventDefault();
        input.focus();
        input.select();
      }
    });
  }

  /* ---- 2. scroll-spy for "On this page" ---- */

  function initSpy() {
    var links = $$(".docs-toc a");
    if (!links.length || !("IntersectionObserver" in window)) return;
    var order = [], by = {}, seen = {};
    links.forEach(function (link) {
      var id = decodeURIComponent(link.hash.slice(1));
      var heading = document.getElementById(id);
      if (heading) { order.push(id); by[id] = { link: link, heading: heading }; }
    });
    var observer = new IntersectionObserver(function (entries) {
      entries.forEach(function (entry) { seen[entry.target.id] = entry.isIntersecting; });
      var current = order.filter(function (id) { return seen[id]; })[0];
      if (!current) return;
      order.forEach(function (id) {
        if (id === current) by[id].link.setAttribute("aria-current", "true");
        else by[id].link.removeAttribute("aria-current");
      });
    }, { rootMargin: "-72px 0px -70% 0px" });
    order.forEach(function (id) { observer.observe(by[id].heading); });
  }

  /* ---- 3. copy buttons and heading links ---- */

  function initCode() {
    if (!navigator.clipboard) return;
    $$(".prose pre").forEach(function (pre) {
      var wrap = document.createElement("div");
      var button = document.createElement("button");
      wrap.className = "codebox";
      button.type = "button";
      button.className = "copy";
      button.textContent = "Copy";
      button.setAttribute("aria-label", "Copy this code");
      button.addEventListener("click", function () {
        navigator.clipboard.writeText(pre.textContent.replace(/\n$/, "")).then(function () {
          button.textContent = "Copied";
          setTimeout(function () { button.textContent = "Copy"; }, 1600);
        });
      });
      pre.parentNode.insertBefore(wrap, pre);
      wrap.appendChild(pre);
      wrap.appendChild(button);
    });
  }

  function initAnchors() {
    $$(".prose h2[id], .prose h3[id]").forEach(function (heading) {
      var link = document.createElement("a");
      link.className = "anchor";
      link.href = "#" + heading.id;
      link.textContent = "#";
      link.setAttribute("aria-label", "Link to this section");
      heading.appendChild(link);
    });
  }

  attempt(initSearch);
  attempt(initSpy);
  attempt(initCode);
  attempt(initAnchors);
})();
