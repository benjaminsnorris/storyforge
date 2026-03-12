/*
 * Storyforge Web Book — Progressive Enhancement
 *
 * The book is fully readable with JavaScript disabled.
 * Everything in this file is optional enhancement.
 *
 * ---------------------------------------------------------------------------
 * INLINE IN <head> — prevents flash of wrong theme.
 * Paste this inside a <script> tag before any stylesheets:
 *
 * (function(){var t=localStorage.getItem('storyforge-theme');if(t)document.documentElement.dataset.theme=t;else if(window.matchMedia('(prefers-color-scheme:dark)').matches)document.documentElement.dataset.theme='dark'})();
 *
 * ---------------------------------------------------------------------------
 */

(function () {
  'use strict';

  // ---------------------------------------------------------------------------
  // Utilities
  // ---------------------------------------------------------------------------

  /** Return a debounced version of fn that waits ms before firing. */
  function debounce(fn, ms) {
    var timer;
    return function () {
      var ctx = this, args = arguments;
      clearTimeout(timer);
      timer = setTimeout(function () { fn.apply(ctx, args); }, ms);
    };
  }

  /** Derive a slug for the current chapter from the URL or body attribute. */
  function getChapterSlug() {
    var slug = document.body.getAttribute('data-chapter');
    if (slug) return slug;
    // Fall back to the last segment of the pathname, minus extension
    var path = window.location.pathname.replace(/\/+$/, '');
    var parts = path.split('/');
    return (parts[parts.length - 1] || 'index').replace(/\.html?$/, '');
  }

  // ---------------------------------------------------------------------------
  // 1. Theme switching
  // ---------------------------------------------------------------------------

  var themes = ['light', 'dark', 'sepia'];

  function currentTheme() {
    return document.documentElement.dataset.theme || 'light';
  }

  function setTheme(theme) {
    document.documentElement.dataset.theme = theme;
    localStorage.setItem('storyforge-theme', theme);
  }

  function cycleTheme() {
    var idx = themes.indexOf(currentTheme());
    setTheme(themes[(idx + 1) % themes.length]);
  }

  var themeBtn = document.querySelector('.theme-toggle');
  if (themeBtn) {
    themeBtn.addEventListener('click', cycleTheme);
  }

  // ---------------------------------------------------------------------------
  // 2. Reading position persistence
  // ---------------------------------------------------------------------------

  var posKey = 'pos-' + getChapterSlug();

  // Restore saved position after layout settles.
  var savedPos = localStorage.getItem(posKey);
  if (savedPos !== null) {
    setTimeout(function () {
      window.scrollTo(0, parseInt(savedPos, 10));
    }, 100);
  }

  // Save position on scroll (debounced).
  window.addEventListener('scroll', debounce(function () {
    localStorage.setItem(posKey, String(window.scrollY));
  }, 500));

  // ---------------------------------------------------------------------------
  // 3. Chapter completion tracking
  // ---------------------------------------------------------------------------

  function getChaptersRead() {
    try { return JSON.parse(localStorage.getItem('chapters-read')) || []; }
    catch (_) { return []; }
  }

  function markChapterRead(slug) {
    var read = getChaptersRead();
    if (read.indexOf(slug) === -1) {
      read.push(slug);
      localStorage.setItem('chapters-read', JSON.stringify(read));
    }
  }

  /** Apply .chapter-read to TOC links whose chapters have been completed. */
  function applyReadClasses() {
    var read = getChaptersRead();
    if (!read.length) return;
    var links = document.querySelectorAll('.toc-overlay a, .toc a');
    for (var i = 0; i < links.length; i++) {
      var href = links[i].getAttribute('href') || '';
      var slug = href.replace(/^.*\//, '').replace(/\.html?$/, '');
      if (read.indexOf(slug) !== -1) {
        links[i].classList.add('chapter-read');
      }
    }
  }

  applyReadClasses();

  // Mark current chapter as read when user scrolls past 90%.
  var chapterMarked = false;
  function checkCompletion() {
    if (chapterMarked) return;
    var scrollTop = window.scrollY;
    var docHeight = document.documentElement.scrollHeight;
    var winHeight = window.innerHeight;
    if (docHeight <= winHeight) return; // page fits in viewport
    if (scrollTop / (docHeight - winHeight) >= 0.9) {
      chapterMarked = true;
      markChapterRead(getChapterSlug());
      applyReadClasses();
    }
  }

  // ---------------------------------------------------------------------------
  // 4. Progress bar
  // ---------------------------------------------------------------------------

  var progressBar = document.querySelector('.progress-bar');

  function updateProgress() {
    if (!progressBar) return;
    var scrollTop = window.scrollY;
    var docHeight = document.documentElement.scrollHeight;
    var winHeight = window.innerHeight;
    var pct = docHeight <= winHeight ? 100 : (scrollTop / (docHeight - winHeight)) * 100;
    progressBar.style.width = Math.min(pct, 100) + '%';
  }

  // ---------------------------------------------------------------------------
  // 5. Auto-hiding navigation
  // ---------------------------------------------------------------------------

  var bookNav = document.querySelector('.book-nav');
  var lastScrollY = window.scrollY;
  var hideTimer = null;

  function handleNavVisibility() {
    var scrollY = window.scrollY;
    if (!bookNav) return;

    // Always visible near the top of the page.
    if (scrollY < 100) {
      bookNav.classList.remove('hidden');
      clearTimeout(hideTimer);
      lastScrollY = scrollY;
      return;
    }

    if (scrollY > lastScrollY) {
      // Scrolling down — hide after 3 seconds.
      clearTimeout(hideTimer);
      hideTimer = setTimeout(function () {
        bookNav.classList.add('hidden');
      }, 3000);
    } else {
      // Scrolling up — show immediately.
      clearTimeout(hideTimer);
      bookNav.classList.remove('hidden');
    }

    lastScrollY = scrollY;
  }

  // ---------------------------------------------------------------------------
  // Unified scroll handler (uses rAF for smooth progress bar updates)
  // ---------------------------------------------------------------------------

  var scrollTicking = false;
  window.addEventListener('scroll', function () {
    if (!scrollTicking) {
      requestAnimationFrame(function () {
        updateProgress();
        checkCompletion();
        handleNavVisibility();
        scrollTicking = false;
      });
      scrollTicking = true;
    }
  });

  // Initial call so progress bar is correct on load.
  updateProgress();

  // ---------------------------------------------------------------------------
  // 6. Keyboard navigation
  // ---------------------------------------------------------------------------

  document.addEventListener('keydown', function (e) {
    // Don't capture when the user is typing in a form field.
    var tag = (e.target.tagName || '').toLowerCase();
    if (tag === 'input' || tag === 'textarea' || tag === 'select' || e.target.isContentEditable) {
      return;
    }

    switch (e.key) {
      case 'ArrowLeft': {
        var prev = document.querySelector('.prev-chapter');
        if (prev && prev.href) window.location.href = prev.href;
        break;
      }
      case 'ArrowRight': {
        var next = document.querySelector('.next-chapter');
        if (next && next.href) window.location.href = next.href;
        break;
      }
      case 't':
      case 'T':
        toggleToc();
        break;
      case 'Escape':
        closeToc();
        break;
    }
  });

  // ---------------------------------------------------------------------------
  // 7. TOC overlay toggle
  // ---------------------------------------------------------------------------

  var tocOverlay = document.querySelector('.toc-overlay');

  function toggleToc() {
    if (!tocOverlay) return;
    tocOverlay.classList.toggle('active');
    if (tocOverlay.classList.contains('active')) {
      var current = tocOverlay.querySelector('.toc-current');
      if (current) {
        setTimeout(function () {
          current.scrollIntoView({ block: 'center', behavior: 'smooth' });
        }, 100);
      }
    }
  }

  function closeToc() {
    if (!tocOverlay) return;
    tocOverlay.classList.remove('active');
  }

  // Close on backdrop click (click on the overlay itself, not its children).
  if (tocOverlay) {
    tocOverlay.addEventListener('click', function (e) {
      if (e.target === tocOverlay) closeToc();
    });
  }

  // ---------------------------------------------------------------------------
  // 8. Chapter info in navigation
  // ---------------------------------------------------------------------------

  var chapterNum = document.body.getAttribute('data-chapter-num');
  var totalChapters = document.body.getAttribute('data-total-chapters');

  if (chapterNum && totalChapters && bookNav) {
    var info = document.createElement('button');
    info.className = 'chapter-info';
    info.textContent = 'Chapter ' + chapterNum + ' of ' + totalChapters;
    info.setAttribute('aria-label', 'Table of contents');
    info.addEventListener('click', toggleToc);
    var navControls = bookNav.querySelector('.nav-controls');
    if (navControls) {
      bookNav.insertBefore(info, navControls);
    } else {
      bookNav.appendChild(info);
    }
  }

  // ---------------------------------------------------------------------------
  // 9. Resume tracking — store last-visited chapter
  // ---------------------------------------------------------------------------

  var currentSlug = getChapterSlug();
  if (currentSlug && currentSlug !== 'index' && currentSlug !== 'contents') {
    localStorage.setItem('storyforge-last-chapter', currentSlug);
  }

  // ---------------------------------------------------------------------------
  // 10. TOC current chapter highlight
  // ---------------------------------------------------------------------------

  function highlightCurrentChapter() {
    var slug = getChapterSlug();
    if (!slug) return;
    var links = document.querySelectorAll('.toc-overlay a, .toc-list a');
    for (var i = 0; i < links.length; i++) {
      var href = links[i].getAttribute('href') || '';
      var linkSlug = href.replace(/^.*\//, '').replace(/\.html?$/, '');
      if (linkSlug === slug) {
        var li = links[i].closest('li');
        if (li) {
          li.classList.add('toc-current');
        }
      }
    }
  }

  highlightCurrentChapter();

})();
