// Storyforge Annotation Overlay — loaded when --annotate is active
(function() {
  'use strict';

  var bookSlug = document.body.dataset.book || 'unknown';
  var chapterSlug = document.body.dataset.chapter || 'unknown';
  var STORAGE_PREFIX = 'storyforge-annotations-' + bookSlug + '-';

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

  function showPopover(x, y, range) {
    removePopover();

    var popover = document.createElement('div');
    popover.className = 'sf-popover';
    popover.style.top = (y + window.scrollY) + 'px';
    popover.style.left = (x + window.scrollX) + 'px';

    var hlBtn = document.createElement('button');
    hlBtn.textContent = 'Highlight';
    hlBtn.addEventListener('click', function(e) {
      e.stopPropagation();
      createHighlightFromRange(range, '');
      removePopover();
    });

    var cmBtn = document.createElement('button');
    cmBtn.textContent = 'Comment';
    cmBtn.addEventListener('click', function(e) {
      e.stopPropagation();
      showCommentInput(popover, range);
    });

    popover.appendChild(hlBtn);
    popover.appendChild(cmBtn);
    document.body.appendChild(popover);
    activePopover = popover;
  }

  function showCommentInput(popover, range) {
    while (popover.firstChild) popover.removeChild(popover.firstChild);

    var wrap = document.createElement('div');
    wrap.className = 'sf-comment-input';

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
      createHighlightFromRange(range, textarea.value.trim());
      removePopover();
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

  function createHighlightFromRange(range, comment) {
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
        createHighlightFromRange(pendingRange, '');
        clearMobileSelection();
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

  function showMobileCommentInput(range) {
    if (!toolbar) return;
    while (toolbar.firstChild) toolbar.removeChild(toolbar.firstChild);

    var wrap = document.createElement('div');
    wrap.className = 'sf-comment-input';
    wrap.style.width = '100%';

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
      createHighlightFromRange(range, textarea.value.trim());
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

    var cancelBtn = document.createElement('button');
    cancelBtn.textContent = 'Cancel';
    cancelBtn.addEventListener('click', function() {
      if (panel.parentNode) panel.parentNode.removeChild(panel);
    });

    var saveBtn = document.createElement('button');
    saveBtn.textContent = 'Save';
    saveBtn.addEventListener('click', function() {
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
    });

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

    if (annotation.selectedText) {
      var quoteP = document.createElement('p');
      quoteP.style.fontStyle = 'italic';
      quoteP.style.color = 'var(--text-dim)';
      var text = annotation.selectedText;
      if (text.length > 100) text = text.slice(0, 100) + '…';
      quoteP.textContent = '\u201c' + text + '\u201d';
      viewer.appendChild(quoteP);
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

    var textarea = document.createElement('textarea');
    textarea.value = annotation.comment || '';
    textarea.rows = 3;
    textarea.style.width = '100%';
    textarea.style.fontFamily = 'inherit';
    textarea.style.fontSize = '0.85rem';
    textarea.style.padding = '6px 8px';
    textarea.style.boxSizing = 'border-box';
    textarea.style.border = '1px solid var(--border)';
    textarea.style.borderRadius = '4px';
    textarea.style.background = 'var(--bg)';
    textarea.style.color = 'var(--text)';

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
      var newComment = textarea.value.trim();
      updateAnnotation(annotation.id, { comment: newComment });
      annotation.comment = newComment;

      // Update has-comment class on highlight span
      var hlSpan = document.querySelector('.sf-highlight[data-annotation-id="' + annotation.id + '"]');
      if (hlSpan) {
        if (newComment) {
          hlSpan.classList.add('has-comment');
        } else {
          hlSpan.classList.remove('has-comment');
        }
      }

      removeViewer();
    });

    actions.appendChild(cancelBtn);
    actions.appendChild(saveBtn);
    viewer.appendChild(textarea);
    viewer.appendChild(actions);

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

    var annotations = loadAnnotations();
    if (annotations.length === 0) {
      btn.textContent = '\u2913';
    } else {
      btn.textContent = '\u2913 ' + annotations.length;
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

  var activeExportMenu = null;

  function showExportMenu(anchorEl) {
    if (activeExportMenu && activeExportMenu.parentNode) {
      activeExportMenu.parentNode.removeChild(activeExportMenu);
      activeExportMenu = null;
      return;
    }

    var menu = document.createElement('div');
    menu.className = 'sf-export-menu';

    var chapterInfo = document.querySelector('.chapter-info');
    var anchor = chapterInfo || anchorEl;
    var rect = anchor.getBoundingClientRect();
    menu.style.position = 'absolute';
    menu.style.top = (rect.bottom + window.scrollY + 4) + 'px';
    menu.style.right = (document.documentElement.clientWidth - rect.right) + 'px';
    menu.style.zIndex = '10001';
    menu.style.background = 'var(--bg, #fff)';
    menu.style.border = '1px solid var(--border, #ccc)';
    menu.style.borderRadius = '6px';
    menu.style.boxShadow = '0 4px 12px rgba(0,0,0,0.15)';
    menu.style.padding = '4px 0';
    menu.style.minWidth = '200px';
    menu.style.fontSize = '0.875rem';

    var options = [
      { label: 'This chapter (JSON)', format: 'chapter-json' },
      { label: 'This chapter (MD)',   format: 'chapter' },
      { label: 'All chapters (JSON)', format: 'json' },
      { label: 'All chapters (MD)',   format: 'md' }
    ];

    options.forEach(function(opt) {
      var btn = document.createElement('button');
      btn.textContent = opt.label;
      btn.style.display = 'block';
      btn.style.width = '100%';
      btn.style.padding = '8px 16px';
      btn.style.textAlign = 'left';
      btn.style.background = 'none';
      btn.style.border = 'none';
      btn.style.cursor = 'pointer';
      btn.style.color = 'var(--text, #000)';
      btn.addEventListener('mouseenter', function() {
        btn.style.background = 'var(--highlight-bg, rgba(0,0,0,0.06))';
      });
      btn.addEventListener('mouseleave', function() {
        btn.style.background = 'none';
      });
      btn.addEventListener('click', function(e) {
        e.stopPropagation();
        doExport(opt.format);
        if (activeExportMenu && activeExportMenu.parentNode) {
          activeExportMenu.parentNode.removeChild(activeExportMenu);
        }
        activeExportMenu = null;
      });
      menu.appendChild(btn);
    });

    document.body.appendChild(menu);
    activeExportMenu = menu;

    function onOutsideClick(e) {
      if (activeExportMenu && !activeExportMenu.contains(e.target) && e.target !== anchorEl) {
        if (activeExportMenu.parentNode) activeExportMenu.parentNode.removeChild(activeExportMenu);
        activeExportMenu = null;
        document.removeEventListener('click', onOutsideClick);
      }
    }
    // Defer to avoid immediately closing from the button click
    setTimeout(function() {
      document.addEventListener('click', onOutsideClick);
    }, 0);
  }

  function addExportButton() {
    var navControls = document.querySelector('.nav-controls');
    if (!navControls) return;

    var btn = document.createElement('button');
    btn.className = 'sf-export-btn';
    btn.textContent = '\u2913';
    btn.title = 'Export annotations';
    btn.setAttribute('aria-label', 'Export annotations');
    btn.style.cursor = 'pointer';

    btn.addEventListener('click', function(e) {
      e.stopPropagation();
      showExportMenu(btn);
    });

    navControls.prepend(btn);
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
    updateBadge();
    addExportButton();
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }

})();
