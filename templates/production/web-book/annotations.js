// Storyforge Annotation Overlay — loaded when --annotate is active
(function() {
  'use strict';

  var bookSlug = document.body.dataset.book || 'unknown';
  var chapterSlug = document.body.dataset.chapter || 'unknown';
  var STORAGE_PREFIX = 'storyforge-annotations-' + bookSlug + '-';

  var HIGHLIGHT_COLORS = [
    { id: 'yellow', label: 'Important', color: '#fcd44f' },
    { id: 'pink', label: 'Needs Revision', color: '#e8819a' },
    { id: 'green', label: 'Strong Passage', color: '#6dca6d' },
    { id: 'blue', label: 'Research Needed', color: '#78b4ff' },
    { id: 'orange', label: 'Cut / Reconsider', color: '#f0a840' }
  ];

  // =========================================================================
  // 1. UUID GENERATOR
  // =========================================================================

  function uuid() {
    return 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, function(c) {
      var r = Math.random() * 16 | 0;
      return (c === 'x' ? r : (r & 0x3 | 0x8)).toString(16);
    });
  }

  // =========================================================================
  // 2. STORAGE FUNCTIONS
  // =========================================================================

  function storageKey() {
    return STORAGE_PREFIX + chapterSlug;
  }

  function loadAnnotations() {
    try {
      var raw = localStorage.getItem(storageKey());
      return raw ? JSON.parse(raw) : [];
    } catch (e) {
      return [];
    }
  }

  function saveAnnotations(annotations) {
    try {
      localStorage.setItem(storageKey(), JSON.stringify(annotations));
    } catch (e) {
      console.warn('[Storyforge Annotations] localStorage full — could not save annotations.', e);
    }
  }

  function addAnnotation(annotation) {
    var annotations = loadAnnotations();
    annotations.push(annotation);
    saveAnnotations(annotations);
    return annotation;
  }

  function updateAnnotation(id, updates) {
    var annotations = loadAnnotations();
    for (var i = 0; i < annotations.length; i++) {
      if (annotations[i].id === id) {
        for (var key in updates) {
          if (Object.prototype.hasOwnProperty.call(updates, key)) {
            annotations[i][key] = updates[key];
          }
        }
        break;
      }
    }
    saveAnnotations(annotations);
  }

  function deleteAnnotation(id) {
    var annotations = loadAnnotations();
    saveAnnotations(annotations.filter(function(a) { return a.id !== id; }));
  }

  // =========================================================================
  // 3. DOM HELPERS
  // =========================================================================

  var BLOCK_SELECTOR = 'p, blockquote, ul, ol, h1, h2, h3, h4, h5, h6';

  function getSceneForNode(node) {
    var el = node.nodeType === Node.TEXT_NODE ? node.parentElement : node;
    while (el && el !== document.body) {
      if (el.dataset && el.dataset.scene !== undefined) {
        return el.dataset.scene;
      }
      el = el.parentElement;
    }
    return null;
  }

  function getParagraphIndex(node, scene) {
    var section = document.querySelector('[data-scene="' + scene + '"]');
    if (!section) return -1;

    var blocks = section.querySelectorAll(BLOCK_SELECTOR);
    var el = node.nodeType === Node.TEXT_NODE ? node.parentElement : node;

    // Walk up to find a direct block child of the section
    while (el && el.parentElement !== section) {
      el = el.parentElement;
    }
    if (!el) return -1;

    for (var i = 0; i < blocks.length; i++) {
      if (blocks[i] === el) return i;
    }
    return -1;
  }

  function getBlockByIndex(scene, index) {
    var section = document.querySelector('[data-scene="' + scene + '"]');
    if (!section) return null;
    var blocks = section.querySelectorAll(BLOCK_SELECTOR);
    return blocks[index] || null;
  }

  // =========================================================================
  // 4. HIGHLIGHT RENDERING
  // =========================================================================

  function renderHighlight(annotation) {
    if (annotation.type === 'margin-note') return;

    var anchor = annotation.anchor;
    if (!anchor) return;

    var block = getBlockByIndex(annotation.scene, anchor.paragraphIndex);
    if (!block) return;

    try {
      // Use TreeWalker to find the text nodes covering the start/end offsets
      // offsets are relative to the block's full text content
      var walker = document.createTreeWalker(block, NodeFilter.SHOW_TEXT, null, false);
      var startNode = null, endNode = null;
      var startOffset = 0, endOffset = 0;
      var charCount = 0;
      var node;

      while ((node = walker.nextNode())) {
        var nodeLen = node.nodeValue.length;
        if (startNode === null && charCount + nodeLen > anchor.startOffset) {
          startNode = node;
          startOffset = anchor.startOffset - charCount;
        }
        if (endNode === null && charCount + nodeLen >= anchor.endOffset) {
          endNode = node;
          endOffset = anchor.endOffset - charCount;
          break;
        }
        charCount += nodeLen;
      }

      if (!startNode || !endNode) return;

      var range = document.createRange();
      range.setStart(startNode, startOffset);
      range.setEnd(endNode, endOffset);

      var span = document.createElement('span');
      span.className = 'sf-highlight';
      if (annotation.comment) span.classList.add('has-comment');
      span.dataset.annotationId = annotation.id;
      span.dataset.color = annotation.color || 'yellow';
      range.surroundContents(span);
    } catch (e) {
      // Cross-element or other range errors — skip silently
    }
  }

  function renderAllHighlights() {
    var annotations = loadAnnotations();
    annotations.forEach(function(a) {
      if (a.type !== 'margin-note') renderHighlight(a);
    });
  }

  // =========================================================================
  // 5. DESKTOP POPOVER
  // =========================================================================

  var activePopover = null;

  function removePopover() {
    if (activePopover && activePopover.parentNode) {
      activePopover.parentNode.removeChild(activePopover);
    }
    activePopover = null;
  }

  function buildColorPicker(onColorClick) {
    var picker = document.createElement('div');
    picker.className = 'sf-color-picker';
    HIGHLIGHT_COLORS.forEach(function(c) {
      var swatch = document.createElement('button');
      swatch.className = 'sf-color-swatch';
      swatch.style.backgroundColor = c.color;
      swatch.title = c.label;
      swatch.dataset.color = c.id;
      swatch.addEventListener('click', function(e) {
        e.stopPropagation();
        onColorClick(c.id);
      });
      picker.appendChild(swatch);
    });
    return picker;
  }

  function showPopover(x, y, range) {
    removePopover();

    var popover = document.createElement('div');
    popover.className = 'sf-popover sf-popover-colors';
    popover.style.top = (y + window.scrollY) + 'px';
    popover.style.left = (x + window.scrollX) + 'px';

    var picker = buildColorPicker(function(colorId) {
      createHighlightFromRange(range, '', colorId);
      removePopover();
    });
    popover.appendChild(picker);

    var noteBtn = document.createElement('button');
    noteBtn.className = 'sf-popover-note';
    noteBtn.textContent = 'Note';
    noteBtn.addEventListener('click', function(e) {
      e.stopPropagation();
      showCommentInput(popover, range);
    });
    popover.appendChild(noteBtn);

    document.body.appendChild(popover);
    activePopover = popover;
  }

  function addTextareaShortcuts(textarea, onSave, onCancel) {
    textarea.addEventListener('keydown', function(e) {
      if ((e.metaKey || e.ctrlKey) && e.key === 'Enter') {
        e.preventDefault();
        onSave();
      } else if (e.key === 'Escape') {
        e.preventDefault();
        onCancel();
      }
    });
  }

  function showCommentInput(popover, range) {
    while (popover.firstChild) popover.removeChild(popover.firstChild);
    popover.className = 'sf-popover';

    var selectedColor = 'yellow';

    var wrap = document.createElement('div');
    wrap.className = 'sf-comment-input';

    var picker = buildColorPicker(function(colorId) {
      selectedColor = colorId;
      var swatches = picker.querySelectorAll('.sf-color-swatch');
      swatches.forEach(function(s) {
        if (s.dataset.color === colorId) s.classList.add('selected');
        else s.classList.remove('selected');
      });
    });
    // Default select yellow
    var defaultSwatch = picker.querySelector('[data-color="yellow"]');
    if (defaultSwatch) defaultSwatch.classList.add('selected');
    wrap.appendChild(picker);

    var textarea = document.createElement('textarea');
    textarea.placeholder = 'Add a comment…';
    textarea.rows = 3;

    var actions = document.createElement('div');
    actions.className = 'sf-actions';

    var cancelBtn = document.createElement('button');
    cancelBtn.textContent = 'Cancel';
    cancelBtn.addEventListener('click', function(e) {
      e.stopPropagation();
      removePopover();
      window.getSelection().removeAllRanges();
    });

    var saveBtn = document.createElement('button');
    saveBtn.textContent = 'Save';
    saveBtn.addEventListener('click', function(e) {
      e.stopPropagation();
      createHighlightFromRange(range, textarea.value.trim(), selectedColor);
      removePopover();
    });

    addTextareaShortcuts(textarea, function() {
      createHighlightFromRange(range, textarea.value.trim(), selectedColor);
      removePopover();
    }, function() {
      removePopover();
      window.getSelection().removeAllRanges();
    });

    actions.appendChild(cancelBtn);
    actions.appendChild(saveBtn);
    wrap.appendChild(textarea);
    wrap.appendChild(actions);
    popover.appendChild(wrap);
    textarea.focus();
  }

  function getTextOffsets(block, range) {
    // Walk text nodes in block to compute character offsets for start/end
    var walker = document.createTreeWalker(block, NodeFilter.SHOW_TEXT, null, false);
    var startOffset = 0, endOffset = 0;
    var charCount = 0;
    var node;

    while ((node = walker.nextNode())) {
      var nodeLen = node.nodeValue.length;
      if (node === range.startContainer) {
        startOffset = charCount + range.startOffset;
      }
      if (node === range.endContainer) {
        endOffset = charCount + range.endOffset;
        break;
      }
      charCount += nodeLen;
    }
    return { startOffset: startOffset, endOffset: endOffset };
  }

  function createHighlightFromRange(range, comment, color) {
    try {
      var startNode = range.startContainer;
      var scene = getSceneForNode(startNode);
      if (!scene) return;

      var paragraphIndex = getParagraphIndex(startNode, scene);
      if (paragraphIndex < 0) return;

      var block = getBlockByIndex(scene, paragraphIndex);
      if (!block) return;

      var offsets = getTextOffsets(block, range);
      var selectedText = range.toString();

      var annotation = {
        id: uuid(),
        type: comment ? 'comment' : 'highlight',
        chapter: chapterSlug,
        scene: scene,
        anchor: {
          paragraphIndex: paragraphIndex,
          startOffset: offsets.startOffset,
          endOffset: offsets.endOffset
        },
        selectedText: selectedText,
        comment: comment,
        color: color || 'yellow',
        createdAt: new Date().toISOString()
      };

      addAnnotation(annotation);
      renderHighlight(annotation);
      updateBadge();
      window.getSelection().removeAllRanges();
    } catch (e) {
      console.warn('[Storyforge Annotations] createHighlightFromRange error:', e);
    }
  }

  // Desktop mouseup listener
  document.addEventListener('mouseup', function(e) {
    if (window.innerWidth < 640) return;
    if (activePopover && activePopover.contains(e.target)) return;

    var selection = window.getSelection();
    if (!selection || selection.isCollapsed || !selection.toString().trim()) return;

    var range = selection.getRangeAt(0);
    var container = range.commonAncestorContainer;
    var el = container.nodeType === Node.TEXT_NODE ? container.parentElement : container;
    if (!el.closest('.chapter-content')) return;

    var rect = range.getBoundingClientRect();
    showPopover(rect.left, rect.top - 50, range.cloneRange());
  });

  // Desktop mousedown listener — close popover when clicking outside
  document.addEventListener('mousedown', function(e) {
    if (window.innerWidth < 640) return;
    if (activePopover && !activePopover.contains(e.target)) {
      removePopover();
    }
  });

  // =========================================================================
  // 6. MOBILE TOOLBAR
  // =========================================================================

  var toolbar = null;
  var pendingRange = null;

  function createToolbar() {
    if (window.innerWidth >= 640) return;
    if (toolbar) return;

    toolbar = document.createElement('div');
    toolbar.className = 'sf-toolbar';

    var hlBtn = document.createElement('button');
    hlBtn.className = 'sf-hidden';
    hlBtn.dataset.action = 'highlight';
    hlBtn.textContent = 'Highlight';
    hlBtn.addEventListener('click', function() {
      if (pendingRange) {
        showMobileColorPicker(pendingRange);
      }
    });

    var cmBtn = document.createElement('button');
    cmBtn.className = 'sf-hidden';
    cmBtn.dataset.action = 'comment';
    cmBtn.textContent = 'Comment';
    cmBtn.addEventListener('click', function() {
      if (pendingRange) {
        showMobileCommentInput(pendingRange);
      }
    });

    var noteBtn = document.createElement('button');
    noteBtn.dataset.action = 'note';
    noteBtn.textContent = '+ Note';
    noteBtn.addEventListener('click', function() {
      showMobileMarginInput();
    });

    toolbar.appendChild(hlBtn);
    toolbar.appendChild(cmBtn);
    toolbar.appendChild(noteBtn);
    document.body.appendChild(toolbar);
  }

  document.addEventListener('selectionchange', function() {
    if (window.innerWidth >= 640) return;
    if (!toolbar) return;

    var selection = window.getSelection();
    if (!selection || selection.isCollapsed || !selection.toString().trim()) {
      // Delay hide to allow tap registration
      setTimeout(function() {
        var sel = window.getSelection();
        if (!sel || sel.isCollapsed || !sel.toString().trim()) {
          var hlBtn = toolbar.querySelector('[data-action="highlight"]');
          var cmBtn = toolbar.querySelector('[data-action="comment"]');
          if (hlBtn) hlBtn.classList.add('sf-hidden');
          if (cmBtn) cmBtn.classList.add('sf-hidden');
        }
      }, 200);
      return;
    }

    var range = selection.getRangeAt(0);
    var container = range.commonAncestorContainer;
    var el = container.nodeType === Node.TEXT_NODE ? container.parentElement : container;
    if (!el.closest('.chapter-content')) return;

    pendingRange = range.cloneRange();
    var hlBtn = toolbar.querySelector('[data-action="highlight"]');
    var cmBtn = toolbar.querySelector('[data-action="comment"]');
    if (hlBtn) hlBtn.classList.remove('sf-hidden');
    if (cmBtn) cmBtn.classList.remove('sf-hidden');
  });

  function clearMobileSelection() {
    window.getSelection().removeAllRanges();
    pendingRange = null;
    if (!toolbar) return;
    var hlBtn = toolbar.querySelector('[data-action="highlight"]');
    var cmBtn = toolbar.querySelector('[data-action="comment"]');
    if (hlBtn) hlBtn.classList.add('sf-hidden');
    if (cmBtn) cmBtn.classList.add('sf-hidden');
  }

  function showMobileColorPicker(range) {
    if (!toolbar) return;
    while (toolbar.firstChild) toolbar.removeChild(toolbar.firstChild);

    var picker = buildColorPicker(function(colorId) {
      createHighlightFromRange(range, '', colorId);
      clearMobileSelection();
      rebuildToolbar();
    });
    toolbar.appendChild(picker);

    var cancelBtn = document.createElement('button');
    cancelBtn.textContent = 'Cancel';
    cancelBtn.style.fontSize = '0.78em';
    cancelBtn.addEventListener('click', function() {
      clearMobileSelection();
      rebuildToolbar();
    });
    toolbar.appendChild(cancelBtn);
  }

  function showMobileCommentInput(range) {
    if (!toolbar) return;
    while (toolbar.firstChild) toolbar.removeChild(toolbar.firstChild);

    var selectedColor = 'yellow';

    var wrap = document.createElement('div');
    wrap.className = 'sf-comment-input';
    wrap.style.width = '100%';

    var picker = buildColorPicker(function(colorId) {
      selectedColor = colorId;
      var swatches = picker.querySelectorAll('.sf-color-swatch');
      swatches.forEach(function(s) {
        if (s.dataset.color === colorId) s.classList.add('selected');
        else s.classList.remove('selected');
      });
    });
    var defaultSwatch = picker.querySelector('[data-color="yellow"]');
    if (defaultSwatch) defaultSwatch.classList.add('selected');
    wrap.appendChild(picker);

    var textarea = document.createElement('textarea');
    textarea.placeholder = 'Add a comment…';
    textarea.rows = 2;

    var actions = document.createElement('div');
    actions.className = 'sf-actions';

    var cancelBtn = document.createElement('button');
    cancelBtn.textContent = 'Cancel';
    cancelBtn.addEventListener('click', function() {
      clearMobileSelection();
      rebuildToolbar();
    });

    var saveBtn = document.createElement('button');
    saveBtn.textContent = 'Save';
    saveBtn.addEventListener('click', function() {
      createHighlightFromRange(range, textarea.value.trim(), selectedColor);
      rebuildToolbar();
    });

    actions.appendChild(cancelBtn);
    actions.appendChild(saveBtn);
    wrap.appendChild(textarea);
    wrap.appendChild(actions);
    toolbar.appendChild(wrap);
    textarea.focus();
  }

  function rebuildToolbar() {
    if (toolbar && toolbar.parentNode) {
      toolbar.parentNode.removeChild(toolbar);
    }
    toolbar = null;
    pendingRange = null;
    createToolbar();
  }

  // =========================================================================
  // 7. MARGIN NOTES
  // =========================================================================

  function setupMarginTriggers() {
    if (window.innerWidth < 640) return; // Desktop only

    var sections = document.querySelectorAll('[data-scene]');
    sections.forEach(function(section) {
      var blocks = section.querySelectorAll(BLOCK_SELECTOR);
      blocks.forEach(function(block, index) {
        block.style.position = 'relative';

        var trigger = document.createElement('button');
        trigger.className = 'sf-margin-trigger';
        trigger.textContent = '+';
        trigger.title = 'Add margin note';
        trigger.setAttribute('aria-label', 'Add margin note');

        var scene = section.dataset.scene;
        trigger.addEventListener('click', function(e) {
          e.stopPropagation();
          showMarginNoteInput(scene, index, block);
        });

        block.appendChild(trigger);
      });
    });
  }

  function showMarginNoteInput(scene, paragraphIndex, block) {
    // Remove any existing note panel
    var existing = document.querySelector('.sf-note-panel');
    if (existing && existing.parentNode) existing.parentNode.removeChild(existing);

    var panel = document.createElement('div');
    panel.className = 'sf-note-panel';

    var textarea = document.createElement('textarea');
    textarea.placeholder = 'Add a margin note…';
    textarea.rows = 3;

    var actions = document.createElement('div');
    actions.className = 'sf-actions';

    function saveMarginNote() {
      var text = textarea.value.trim();
      if (!text) return;

      var annotation = {
        id: uuid(),
        type: 'margin-note',
        chapter: chapterSlug,
        scene: scene,
        anchor: { paragraphIndex: paragraphIndex },
        comment: text,
        createdAt: new Date().toISOString()
      };

      addAnnotation(annotation);
      if (panel.parentNode) panel.parentNode.removeChild(panel);
      renderMarginIndicator(annotation, block);
      updateBadge();
    }

    function cancelMarginNote() {
      if (panel.parentNode) panel.parentNode.removeChild(panel);
    }

    var cancelBtn = document.createElement('button');
    cancelBtn.textContent = 'Cancel';
    cancelBtn.addEventListener('click', cancelMarginNote);

    var saveBtn = document.createElement('button');
    saveBtn.textContent = 'Save';
    saveBtn.addEventListener('click', saveMarginNote);

    addTextareaShortcuts(textarea, saveMarginNote, cancelMarginNote);

    actions.appendChild(cancelBtn);
    actions.appendChild(saveBtn);
    panel.appendChild(textarea);
    panel.appendChild(actions);

    block.insertAdjacentElement('afterend', panel);
    textarea.focus();
  }

  function showMobileMarginInput() {
    var viewportCenter = window.innerHeight / 2;
    var sections = document.querySelectorAll('[data-scene]');
    var closestBlock = null;
    var closestScene = null;
    var closestIndex = -1;
    var closestDist = Infinity;

    sections.forEach(function(section) {
      var blocks = section.querySelectorAll(BLOCK_SELECTOR);
      blocks.forEach(function(block, index) {
        var rect = block.getBoundingClientRect();
        var blockCenter = (rect.top + rect.bottom) / 2;
        var dist = Math.abs(blockCenter - viewportCenter);
        if (dist < closestDist) {
          closestDist = dist;
          closestBlock = block;
          closestScene = section.dataset.scene;
          closestIndex = index;
        }
      });
    });

    if (closestBlock) {
      showMarginNoteInput(closestScene, closestIndex, closestBlock);
    }
  }

  function renderMarginIndicator(annotation, block) {
    var indicator = document.createElement('span');
    indicator.className = 'sf-margin-indicator';
    indicator.textContent = '✎';
    indicator.dataset.annotationId = annotation.id;
    indicator.title = annotation.comment;
    indicator.setAttribute('role', 'button');
    indicator.setAttribute('tabindex', '0');
    indicator.addEventListener('click', function(e) {
      e.stopPropagation();
      showCommentViewer(annotation, indicator);
    });
    block.style.position = 'relative';
    block.appendChild(indicator);
  }

  function renderAllMarginNotes() {
    var annotations = loadAnnotations();
    annotations.forEach(function(a) {
      if (a.type !== 'margin-note') return;
      var block = getBlockByIndex(a.scene, a.anchor.paragraphIndex);
      if (block) renderMarginIndicator(a, block);
    });
  }

  // =========================================================================
  // 8. COMMENT VIEWER
  // =========================================================================

  var activeViewer = null;

  function removeViewer() {
    if (activeViewer && activeViewer.parentNode) {
      activeViewer.parentNode.removeChild(activeViewer);
    }
    activeViewer = null;
  }

  function showCommentViewer(annotation, targetEl) {
    removeViewer();

    var viewer = document.createElement('div');
    viewer.className = 'sf-comment-viewer';

    var rect = targetEl.getBoundingClientRect();
    viewer.style.top = (rect.bottom + window.scrollY + 6) + 'px';
    viewer.style.left = (rect.left + window.scrollX) + 'px';

    if (annotation.comment) {
      var commentP = document.createElement('p');
      commentP.textContent = annotation.comment;
      viewer.appendChild(commentP);
    }

    if (annotation.selectedText && (annotation.comment || annotation.type === 'margin-note')) {
      var quoteP = document.createElement('p');
      quoteP.style.fontStyle = 'italic';
      quoteP.style.color = 'var(--text-dim)';
      var text = annotation.selectedText;
      if (text.length > 100) text = text.slice(0, 100) + '…';
      quoteP.textContent = '\u201c' + text + '\u201d';
      viewer.appendChild(quoteP);
    }

    if (annotation.createdAt) {
      var timeEl = document.createElement('time');
      timeEl.className = 'sf-timestamp';
      var date = new Date(annotation.createdAt);
      var months = ['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec'];
      var hours = date.getHours();
      var minutes = date.getMinutes();
      var ampm = hours >= 12 ? 'pm' : 'am';
      hours = hours % 12 || 12;
      var minStr = minutes < 10 ? '0' + minutes : minutes;
      timeEl.textContent = months[date.getMonth()] + ' ' + date.getDate() + ', ' + date.getFullYear() + ' at ' + hours + ':' + minStr + ' ' + ampm;
      timeEl.setAttribute('datetime', annotation.createdAt);
      viewer.appendChild(timeEl);
    }

    // Color picker for highlights/comments (not margin notes)
    if (annotation.type !== 'margin-note') {
      var colorRow = document.createElement('div');
      colorRow.className = 'sf-color-picker';
      colorRow.style.marginBottom = '8px';
      HIGHLIGHT_COLORS.forEach(function(c) {
        var swatch = document.createElement('button');
        swatch.className = 'sf-color-swatch';
        if ((annotation.color || 'yellow') === c.id) swatch.classList.add('selected');
        swatch.style.backgroundColor = c.color;
        swatch.title = c.label;
        swatch.addEventListener('click', function(e) {
          e.stopPropagation();
          annotation.color = c.id;
          updateAnnotation(annotation.id, { color: c.id });
          var hlSpan = document.querySelector('.sf-highlight[data-annotation-id="' + annotation.id + '"]');
          if (hlSpan) hlSpan.dataset.color = c.id;
          // Update selected state
          colorRow.querySelectorAll('.sf-color-swatch').forEach(function(s) { s.classList.remove('selected'); });
          swatch.classList.add('selected');
          updateBadge();
        });
        colorRow.appendChild(swatch);
      });
      viewer.appendChild(colorRow);
    }

    var actions = document.createElement('div');
    actions.className = 'sf-actions';

    var editBtn = document.createElement('button');
    editBtn.textContent = 'Edit';
    editBtn.addEventListener('click', function(e) {
      e.stopPropagation();
      showEditInput(annotation, targetEl);
    });

    var deleteBtn = document.createElement('button');
    deleteBtn.className = 'sf-delete';
    deleteBtn.textContent = 'Delete';
    deleteBtn.addEventListener('click', function(e) {
      e.stopPropagation();
      deleteAnnotation(annotation.id);

      // Unwrap highlight span or remove margin indicator
      var hlSpan = document.querySelector('.sf-highlight[data-annotation-id="' + annotation.id + '"]');
      if (hlSpan) {
        while (hlSpan.firstChild) hlSpan.parentNode.insertBefore(hlSpan.firstChild, hlSpan);
        hlSpan.parentNode.removeChild(hlSpan);
      }
      var indicator = document.querySelector('.sf-margin-indicator[data-annotation-id="' + annotation.id + '"]');
      if (indicator && indicator.parentNode) indicator.parentNode.removeChild(indicator);

      removeViewer();
      updateBadge();
    });

    var closeBtn = document.createElement('button');
    closeBtn.textContent = 'Close';
    closeBtn.addEventListener('click', function(e) {
      e.stopPropagation();
      removeViewer();
    });

    actions.appendChild(editBtn);
    actions.appendChild(deleteBtn);
    actions.appendChild(closeBtn);
    viewer.appendChild(actions);

    document.body.appendChild(viewer);
    activeViewer = viewer;
  }

  function showEditInput(annotation, targetEl) {
    removeViewer();

    var viewer = document.createElement('div');
    viewer.className = 'sf-comment-viewer';

    var rect = targetEl.getBoundingClientRect();
    viewer.style.top = (rect.bottom + window.scrollY + 6) + 'px';
    viewer.style.left = (rect.left + window.scrollX) + 'px';

    var wrap = document.createElement('div');
    wrap.className = 'sf-comment-input';

    var textarea = document.createElement('textarea');
    textarea.value = annotation.comment || '';
    textarea.placeholder = 'Add a comment…';
    textarea.rows = 3;

    function saveEdit() {
      var newComment = textarea.value.trim();
      updateAnnotation(annotation.id, { comment: newComment });
      annotation.comment = newComment;

      var hlSpan = document.querySelector('.sf-highlight[data-annotation-id="' + annotation.id + '"]');
      if (hlSpan) {
        if (newComment) {
          hlSpan.classList.add('has-comment');
        } else {
          hlSpan.classList.remove('has-comment');
        }
      }

      removeViewer();
    }

    var actions = document.createElement('div');
    actions.className = 'sf-actions';

    var cancelBtn = document.createElement('button');
    cancelBtn.textContent = 'Cancel';
    cancelBtn.addEventListener('click', function(e) {
      e.stopPropagation();
      removeViewer();
    });

    var saveBtn = document.createElement('button');
    saveBtn.textContent = 'Save';
    saveBtn.addEventListener('click', function(e) {
      e.stopPropagation();
      saveEdit();
    });

    addTextareaShortcuts(textarea, saveEdit, removeViewer);

    actions.appendChild(cancelBtn);
    actions.appendChild(saveBtn);
    wrap.appendChild(textarea);
    wrap.appendChild(actions);
    viewer.appendChild(wrap);

    document.body.appendChild(viewer);
    activeViewer = viewer;
    textarea.focus();
  }

  // Click listener: open viewer on highlight/indicator, close when clicking outside
  document.addEventListener('click', function(e) {
    var hlSpan = e.target.closest('.sf-highlight');
    var indicator = e.target.closest('.sf-margin-indicator');

    if (hlSpan) {
      var annotationId = hlSpan.dataset.annotationId;
      var annotations = loadAnnotations();
      var annotation = null;
      for (var i = 0; i < annotations.length; i++) {
        if (annotations[i].id === annotationId) { annotation = annotations[i]; break; }
      }
      if (annotation) showCommentViewer(annotation, hlSpan);
      return;
    }

    if (indicator) {
      // Already handled by indicator's own click listener
      return;
    }

    if (activeViewer && !activeViewer.contains(e.target)) {
      removeViewer();
    }
  });

  // =========================================================================
  // 9. BADGE
  // =========================================================================

  function updateBadge() {
    var btn = document.querySelector('.sf-export-btn');
    if (!btn) return;

    var svg = btn.querySelector('svg');
    // Remove any existing count span
    var existing = btn.querySelector('.sf-count');
    if (existing) existing.parentNode.removeChild(existing);

    var annotations = loadAnnotations();
    if (annotations.length > 0) {
      var count = document.createElement('span');
      count.className = 'sf-count';
      count.style.fontSize = '0.75em';
      count.textContent = ' ' + annotations.length;
      btn.appendChild(count);
    }

    // Refresh sidebar list if open
    if (sidebarEl && sidebarEl.classList.contains('active')) {
      renderSidebarList();
    }
  }

  // =========================================================================
  // 10. ANCHOR RE-VALIDATION
  // =========================================================================

  function revalidateAnchors() {
    var annotations = loadAnnotations();
    var stale = [];
    var valid = [];

    annotations.forEach(function(annotation) {
      if (annotation.type === 'margin-note') {
        var block = getBlockByIndex(annotation.scene, annotation.anchor.paragraphIndex);
        if (!block) {
          stale.push(annotation);
        } else {
          valid.push(annotation);
        }
        return;
      }

      // highlight or comment
      var block = getBlockByIndex(annotation.scene, annotation.anchor.paragraphIndex);
      if (block && block.textContent.indexOf(annotation.selectedText) !== -1) {
        // Still valid at stored location
        valid.push(annotation);
        return;
      }

      // Try scanning +/- 3 paragraphs
      var found = false;
      for (var delta = -3; delta <= 3; delta++) {
        if (delta === 0) continue;
        var altIndex = annotation.anchor.paragraphIndex + delta;
        if (altIndex < 0) continue;
        var altBlock = getBlockByIndex(annotation.scene, altIndex);
        if (altBlock && altBlock.textContent.indexOf(annotation.selectedText) !== -1) {
          // Re-anchor: update paragraphIndex
          var textIdx = altBlock.textContent.indexOf(annotation.selectedText);
          annotation.anchor.paragraphIndex = altIndex;
          annotation.anchor.startOffset = textIdx;
          annotation.anchor.endOffset = textIdx + annotation.selectedText.length;
          valid.push(annotation);
          found = true;
          break;
        }
      }

      if (!found) {
        stale.push(annotation);
      }
    });

    saveAnnotations(valid);
    return stale;
  }

  function renderStalePanel(staleAnnotations) {
    if (!staleAnnotations || staleAnnotations.length === 0) return;

    var chapterContent = document.querySelector('.chapter-content');
    if (!chapterContent) return;

    var panel = document.createElement('div');
    panel.className = 'sf-stale-panel';

    var heading = document.createElement('h3');
    heading.textContent = staleAnnotations.length + ' annotation' +
      (staleAnnotations.length !== 1 ? 's' : '') +
      ' could not be placed (text may have changed)';
    panel.appendChild(heading);

    staleAnnotations.forEach(function(annotation) {
      var details = document.createElement('details');

      var summary = document.createElement('summary');
      summary.textContent = annotation.type.charAt(0).toUpperCase() +
        annotation.type.slice(1).replace('-', ' ');
      details.appendChild(summary);

      if (annotation.selectedText) {
        var quote = document.createElement('blockquote');
        quote.textContent = annotation.selectedText;
        details.appendChild(quote);
      }

      if (annotation.comment) {
        var commentP = document.createElement('p');
        commentP.textContent = annotation.comment;
        commentP.style.fontSize = '0.8rem';
        commentP.style.margin = '4px 0';
        details.appendChild(commentP);
      }

      var deleteBtn = document.createElement('button');
      deleteBtn.textContent = 'Delete';
      deleteBtn.addEventListener('click', function() {
        deleteAnnotation(annotation.id);
        if (details.parentNode) details.parentNode.removeChild(details);
        var remaining = panel.querySelectorAll('details');
        if (remaining.length === 0 && panel.parentNode) {
          panel.parentNode.removeChild(panel);
        }
        updateBadge();
      });
      details.appendChild(deleteBtn);

      panel.appendChild(details);
    });

    chapterContent.appendChild(panel);
  }

  // =========================================================================
  // 11. EXPORT
  // =========================================================================

  function getAllAnnotations() {
    var all = [];
    try {
      for (var i = 0; i < localStorage.length; i++) {
        var key = localStorage.key(i);
        if (key && key.indexOf(STORAGE_PREFIX) === 0) {
          var chSlug = key.slice(STORAGE_PREFIX.length);
          var raw = localStorage.getItem(key);
          if (!raw) continue;
          var parsed = JSON.parse(raw);
          parsed.forEach(function(a) {
            if (!a.chapter) a.chapter = chSlug;
          });
          all = all.concat(parsed);
        }
      }
    } catch (e) {
      console.warn('[Storyforge Annotations] getAllAnnotations error:', e);
    }

    all.sort(function(a, b) {
      if (a.chapter < b.chapter) return -1;
      if (a.chapter > b.chapter) return 1;
      if (a.scene < b.scene) return -1;
      if (a.scene > b.scene) return 1;
      return (a.anchor.paragraphIndex || 0) - (b.anchor.paragraphIndex || 0);
    });

    return all;
  }

  function exportJSON(annotations) {
    var titleEl = document.querySelector('.nav-title');
    var bookTitle = titleEl ? titleEl.textContent.trim() : bookSlug;
    return JSON.stringify({
      book: bookTitle,
      exportedAt: new Date().toISOString(),
      annotator: 'author',
      annotations: annotations
    }, null, 2);
  }

  function exportMarkdown(annotations) {
    // Build chapter title lookup from TOC links
    var chapterTitles = {};
    var tocLinks = document.querySelectorAll('.toc-contents a');
    tocLinks.forEach(function(link) {
      var href = link.getAttribute('href') || '';
      var match = href.match(/chapters\/(chapter-\d+)\.html/);
      if (match) {
        chapterTitles[match[1]] = link.textContent.trim();
      }
    });

    var titleEl = document.querySelector('.nav-title');
    var bookTitle = titleEl ? titleEl.textContent.trim() : bookSlug;
    var dateStr = new Date().toISOString().slice(0, 10);

    var lines = [];
    lines.push('# Annotations: ' + bookTitle);
    lines.push('Exported: ' + dateStr);
    lines.push('');

    var currentChapter = null;
    var currentScene = null;

    annotations.forEach(function(a) {
      if (a.chapter !== currentChapter) {
        currentChapter = a.chapter;
        currentScene = null;
        var chNum = (currentChapter.match(/chapter-(\d+)/) || [])[1] || '';
        var chTitle = chapterTitles[currentChapter] ||
          (chNum ? 'Chapter ' + chNum : currentChapter);
        lines.push('## ' + chTitle);
        lines.push('');
      }

      if (a.scene !== currentScene) {
        currentScene = a.scene;
        lines.push('### Scene: ' + currentScene);
        lines.push('');
      }

      if (a.type === 'margin-note') {
        lines.push('*(margin note)*');
      }

      if (a.selectedText) {
        lines.push('> \u201c' + a.selectedText + '\u201d');
      }

      if (a.comment) {
        lines.push(a.comment);
      }

      lines.push('');
    });

    return lines.join('\n');
  }

  function downloadFile(content, filename, mimeType) {
    var blob = new Blob([content], { type: mimeType });
    var url = URL.createObjectURL(blob);
    var a = document.createElement('a');
    a.href = url;
    a.download = filename;
    a.style.display = 'none';
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
  }

  function doExport(format) {
    var annotations, content, filename;

    if (format === 'chapter-json') {
      annotations = loadAnnotations();
      content = exportJSON(annotations);
      filename = bookSlug + '-' + chapterSlug + '-annotations.json';
      downloadFile(content, filename, 'application/json');
    } else if (format === 'chapter') {
      annotations = loadAnnotations();
      content = exportMarkdown(annotations);
      filename = bookSlug + '-' + chapterSlug + '-annotations.md';
      downloadFile(content, filename, 'text/markdown');
    } else if (format === 'json') {
      annotations = getAllAnnotations();
      content = exportJSON(annotations);
      filename = bookSlug + '-annotations.json';
      downloadFile(content, filename, 'application/json');
    } else if (format === 'md') {
      annotations = getAllAnnotations();
      content = exportMarkdown(annotations);
      filename = bookSlug + '-annotations.md';
      downloadFile(content, filename, 'text/markdown');
    }
  }

  // =========================================================================
  // 11b. ANNOTATION SIDEBAR
  // =========================================================================

  var sidebarEl = null;
  var sidebarFilter = null;

  function toggleSidebar() {
    if (sidebarEl && sidebarEl.classList.contains('active')) {
      closeSidebar();
    } else {
      openSidebar();
    }
  }

  function openSidebar() {
    if (!sidebarEl) buildSidebar();
    renderSidebarList();
    sidebarEl.classList.add('active');
  }

  function closeSidebar() {
    if (sidebarEl) sidebarEl.classList.remove('active');
  }

  function buildSidebar() {
    sidebarEl = document.createElement('div');
    sidebarEl.className = 'sf-sidebar';

    // Header
    var header = document.createElement('div');
    header.className = 'sf-sidebar-header';

    var title = document.createElement('h3');
    title.textContent = 'Annotations';
    header.appendChild(title);

    var closeBtn = document.createElement('button');
    closeBtn.className = 'sf-sidebar-close';
    closeBtn.innerHTML = '&times;';
    closeBtn.addEventListener('click', closeSidebar);
    header.appendChild(closeBtn);

    sidebarEl.appendChild(header);

    // Color legend / filters
    var filters = document.createElement('div');
    filters.className = 'sf-sidebar-filters';

    var allBtn = document.createElement('button');
    allBtn.className = 'sf-filter-row sf-filter-all selected';
    allBtn.textContent = 'All';
    allBtn.addEventListener('click', function() {
      sidebarFilter = null;
      updateFilterUI();
      renderSidebarList();
    });
    filters.appendChild(allBtn);

    HIGHLIGHT_COLORS.forEach(function(c) {
      var row = document.createElement('button');
      row.className = 'sf-filter-row sf-filter-swatch';
      row.dataset.color = c.id;
      row.addEventListener('click', function() {
        sidebarFilter = (sidebarFilter === c.id) ? null : c.id;
        updateFilterUI();
        renderSidebarList();
      });

      var dot = document.createElement('span');
      dot.className = 'sf-filter-dot';
      dot.style.backgroundColor = c.color;
      row.appendChild(dot);

      var label = document.createElement('span');
      label.className = 'sf-filter-label';
      label.textContent = c.label;
      row.appendChild(label);

      filters.appendChild(row);
    });

    sidebarEl.appendChild(filters);

    // List container
    var list = document.createElement('div');
    list.className = 'sf-sidebar-list';
    sidebarEl.appendChild(list);

    // Footer with export links
    var footer = document.createElement('div');
    footer.className = 'sf-sidebar-footer';

    var exportLabel = document.createElement('span');
    exportLabel.textContent = 'Export: ';
    exportLabel.style.color = 'var(--text-dim)';
    exportLabel.style.fontSize = '0.78em';
    footer.appendChild(exportLabel);

    ['chapter-json', 'chapter', 'json', 'md'].forEach(function(fmt, i) {
      var labels = { 'chapter-json': 'Chapter JSON', 'chapter': 'Chapter MD', 'json': 'All JSON', 'md': 'All MD' };
      if (i > 0) {
        var sep = document.createElement('span');
        sep.textContent = ' \u00b7 ';
        sep.style.color = 'var(--text-dim)';
        sep.style.fontSize = '0.78em';
        footer.appendChild(sep);
      }
      var link = document.createElement('a');
      link.href = '#';
      link.textContent = labels[fmt];
      link.style.color = 'var(--accent)';
      link.style.fontSize = '0.78em';
      link.style.textDecoration = 'none';
      link.addEventListener('click', function(e) {
        e.preventDefault();
        doExport(fmt);
      });
      footer.appendChild(link);
    });

    sidebarEl.appendChild(footer);
    document.body.appendChild(sidebarEl);
  }

  function updateFilterUI() {
    if (!sidebarEl) return;
    var allBtn = sidebarEl.querySelector('.sf-filter-all');
    var swatches = sidebarEl.querySelectorAll('.sf-filter-swatch');
    if (allBtn) {
      if (sidebarFilter === null) allBtn.classList.add('selected');
      else allBtn.classList.remove('selected');
    }
    swatches.forEach(function(s) {
      if (s.dataset.color === sidebarFilter) s.classList.add('selected');
      else s.classList.remove('selected');
    });
  }

  function renderSidebarList() {
    if (!sidebarEl) return;
    var list = sidebarEl.querySelector('.sf-sidebar-list');
    if (!list) return;
    while (list.firstChild) list.removeChild(list.firstChild);

    var annotations = loadAnnotations();

    if (sidebarFilter) {
      annotations = annotations.filter(function(a) {
        return (a.color || 'yellow') === sidebarFilter;
      });
    }

    if (annotations.length === 0) {
      var empty = document.createElement('p');
      empty.className = 'sf-sidebar-empty';
      empty.textContent = sidebarFilter ? 'No ' + sidebarFilter + ' annotations' : 'No annotations yet';
      list.appendChild(empty);
      return;
    }

    annotations.forEach(function(annotation) {
      var card = document.createElement('div');
      card.className = 'sf-sidebar-card';
      card.addEventListener('click', function() {
        scrollToAnnotation(annotation);
        if (window.innerWidth < 640) closeSidebar();
      });

      // Color dot
      var dot = document.createElement('span');
      dot.className = 'sf-sidebar-dot';
      var colorObj = HIGHLIGHT_COLORS.find(function(c) { return c.id === (annotation.color || 'yellow'); });
      dot.style.backgroundColor = colorObj ? colorObj.color : '#fcd44f';
      card.appendChild(dot);

      var content = document.createElement('div');
      content.className = 'sf-sidebar-card-content';

      // Selected text
      if (annotation.selectedText) {
        var textEl = document.createElement('p');
        textEl.className = 'sf-sidebar-text';
        var t = annotation.selectedText;
        if (t.length > 60) t = t.slice(0, 60) + '\u2026';
        textEl.textContent = '\u201c' + t + '\u201d';
        content.appendChild(textEl);
      }

      // Comment
      if (annotation.comment) {
        var commentEl = document.createElement('p');
        commentEl.className = 'sf-sidebar-comment';
        var c = annotation.comment;
        if (c.length > 80) c = c.slice(0, 80) + '\u2026';
        commentEl.textContent = c;
        content.appendChild(commentEl);
      }

      // Type label for margin notes
      if (annotation.type === 'margin-note') {
        var typeEl = document.createElement('span');
        typeEl.className = 'sf-sidebar-type';
        typeEl.textContent = 'Margin note';
        content.appendChild(typeEl);
      }

      // Timestamp
      if (annotation.createdAt) {
        var timeEl = document.createElement('time');
        timeEl.className = 'sf-sidebar-time';
        var date = new Date(annotation.createdAt);
        var months = ['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec'];
        timeEl.textContent = months[date.getMonth()] + ' ' + date.getDate();
        content.appendChild(timeEl);
      }

      card.appendChild(content);
      list.appendChild(card);
    });
  }

  function scrollToAnnotation(annotation) {
    var el = null;
    if (annotation.type === 'margin-note') {
      el = document.querySelector('.sf-margin-indicator[data-annotation-id="' + annotation.id + '"]');
    } else {
      el = document.querySelector('.sf-highlight[data-annotation-id="' + annotation.id + '"]');
    }
    if (!el) return;

    el.scrollIntoView({ behavior: 'smooth', block: 'center' });
    el.classList.add('sf-flash');
    setTimeout(function() { el.classList.remove('sf-flash'); }, 1200);
  }

  // Close sidebar on outside click
  document.addEventListener('click', function(e) {
    if (!sidebarEl || !sidebarEl.classList.contains('active')) return;
    if (sidebarEl.contains(e.target)) return;
    var toggleBtn = document.querySelector('.sf-export-btn');
    if (toggleBtn && (toggleBtn === e.target || toggleBtn.contains(e.target))) return;
    closeSidebar();
  });

  // Close sidebar on Escape
  document.addEventListener('keydown', function(e) {
    if (e.key === 'Escape' && sidebarEl && sidebarEl.classList.contains('active')) {
      closeSidebar();
    }
  });

  function addExportButton() {
    var navControls = document.querySelector('.nav-controls');
    if (!navControls) return;

    var btn = document.createElement('button');
    btn.className = 'sf-export-btn';
    btn.innerHTML = '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/></svg>';
    btn.title = 'Annotations';
    btn.setAttribute('aria-label', 'Annotations');

    btn.addEventListener('click', function(e) {
      e.stopPropagation();
      toggleSidebar();
    });

    var chapterInfo = navControls.querySelector('.chapter-info');
    if (chapterInfo) {
      navControls.insertBefore(btn, chapterInfo);
    } else {
      var themeToggle = navControls.querySelector('.theme-toggle');
      if (themeToggle) {
        navControls.insertBefore(btn, themeToggle);
      } else {
        navControls.appendChild(btn);
      }
    }
  }

  // =========================================================================
  // 12. INIT
  // =========================================================================

  function init() {
    var stale = revalidateAnchors();
    renderAllHighlights();
    renderAllMarginNotes();
    renderStalePanel(stale);
    setupMarginTriggers();
    createToolbar();
    addExportButton();
    updateBadge();
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }

})();
