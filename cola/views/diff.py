from PyQt4 import QtGui
from PyQt4 import QtCore
from PyQt4.QtCore import Qt, SIGNAL

import cola
import os
from cola import guicmds
from cola import signals
from cola.qtutils import add_action, question, SLOT
from cola.views.syntax import DiffSyntaxHighlighter


class DiffTextEdit(QtGui.QTextEdit):
    def __init__(self, parent):
        QtGui.QTextEdit.__init__(self, parent)
        self.model = cola.model()
        self.setMinimumSize(QtCore.QSize(1, 1))
        self.setLineWrapMode(QtGui.QTextEdit.NoWrap)
        self.setAcceptRichText(False)
        self.setCursorWidth(2)

        self.setTextInteractionFlags(Qt.TextSelectableByKeyboard |
                                     Qt.TextSelectableByMouse)
        # Diff/patch syntax highlighter
        self.syntax = DiffSyntaxHighlighter(self.document())

        # Install diff shortcut keys for stage/unstage
        self.action_process_hunk = add_action(self, 'Process Hunk',
                   self.apply_hunk, QtCore.Qt.Key_H)
        self.action_process_selection = add_action(self, 'Process Selection',
                   self.apply_selection, QtCore.Qt.Key_S)
        # Context menu actions
        self.action_stage_selection = add_action(self,
                self.tr('Stage &Selected Lines'),
                self.stage_hunk_selection)
        self.action_undo_selection = add_action(self,
                self.tr('Undo Selected Lines'),
                self.undo_selection)
        self.action_unstage_selection = add_action(self,
                self.tr('Unstage &Selected Lines'),
                self.unstage_hunk_selection)
        self.action_apply_selection = add_action(self,
                self.tr('Apply Diff Selection to Work Tree'),
                self.stage_hunk_selection)

        cola.notifier().connect(signals.diff_text, self.setPlainText)
        self.connect(self, SIGNAL('copyAvailable(bool)'),
                     self.enable_selection_actions)

    # Qt overrides
    def contextMenuEvent(self, event):
        """Create the context menu for the diff display."""
        menu = QtGui.QMenu(self)
        staged, modified, unmerged, untracked = cola.selection()

        if self.mode == self.model.mode_worktree:
            if modified and modified[0] in cola.model().submodules:
                menu.addAction(self.tr('Stage'),
                               SLOT(signals.stage, modified))
                menu.addAction(self.tr('Launch git-cola'),
                               SLOT(signals.open_repo,
                                    os.path.abspath(modified[0])))
            elif modified:
                menu.addAction(self.tr('Stage &Hunk For Commit'),
                               self.stage_hunk)
                menu.addAction(self.action_stage_selection)
                menu.addSeparator()
                menu.addAction(self.tr('Undo Hunk'),
                               self.undo_hunk)
                menu.addAction(self.action_undo_selection)

        elif self.mode == self.model.mode_index:
            if staged and staged[0] in cola.model().submodules:
                menu.addAction(self.tr('Unstage'),
                               SLOT(signals.unstage, staged))
                menu.addAction(self.tr('Launch git-cola'),
                               SLOT(signals.open_repo,
                                    os.path.abspath(staged[0])))
            else:
                menu.addAction(self.tr('Unstage &Hunk From Commit'),
                               self.unstage_hunk)
                menu.addAction(self.action_unstage_selection)

        elif self.mode == self.model.mode_branch:
            menu.addAction(self.tr('Apply Diff to Work Tree'),
                           self.stage_hunk)
            menu.addAction(self.action_apply_selection)

        elif self.mode == self.model.mode_grep:
            menu.addAction(self.tr('Go Here'),
                           lambda: guicmds.goto_grep(self.selected_line()))

        menu.addSeparator()
        add_action(menu, 'Copy', self.copy)
        menu.addAction('Copy', self.copy)
        menu.addAction('Select All', self.selectAll)
        menu.exec_(self.mapToGlobal(event.pos()))

    def setPlainText(self, text):
        """setPlainText(str) while retaining scrollbar positions"""
        scrollbar = self.verticalScrollBar()
        if scrollbar:
            scrollvalue = scrollbar.value()
        if text is not None:
            QtGui.QTextEdit.setPlainText(self, text)
            if scrollbar:
                scrollbar.setValue(scrollvalue)

    # Accessors
    mode = property(lambda self: self.model.mode)

    def offset_and_selection(self):
        cursor = self.textCursor()
        offset = cursor.position()
        selection = unicode(cursor.selection().toPlainText())
        return offset, selection

    def selected_line(self):
        cursor = self.textCursor()
        offset = cursor.position()
        contents = unicode(self.toPlainText())
        while (offset >= 1
                and contents[offset-1]
                and contents[offset-1] != '\n'):
            offset -= 1
        data = contents[offset:]
        if '\n' in data:
            line, rest = data.split('\n', 1)
        else:
            line = data
        return line

    # Mutators
    def enable_selection_actions(self, enabled):
        self.action_apply_selection.setEnabled(enabled)
        self.action_undo_selection.setEnabled(enabled)
        self.action_unstage_selection.setEnabled(enabled)
        self.action_stage_selection.setEnabled(enabled)

    def apply_hunk(self):
        staged, modified, unmerged, untracked = cola.single_selection()
        if self.mode == self.model.mode_worktree and modified:
            self.stage_hunk()
        elif self.mode == self.model.mode_index:
            self.unstage_hunk()

    def apply_selection(self):
        staged, modified, unmerged, untracked = cola.single_selection()
        if self.mode == self.model.mode_worktree and modified:
            self.stage_hunk_selection()
        elif self.mode == self.model.mode_index:
            self.unstage_hunk_selection()

    def stage_hunk(self):
        """Stage a specific hunk."""
        self.process_diff_selection(staged=False)

    def stage_hunk_selection(self):
        """Stage selected lines."""
        self.process_diff_selection(staged=False, selected=True)

    def unstage_hunk(self, cached=True):
        """Unstage a hunk."""
        self.process_diff_selection(staged=True)

    def unstage_hunk_selection(self):
        """Unstage selected lines."""
        self.process_diff_selection(staged=True, selected=True)

    def undo_hunk(self):
        """Destructively remove a hunk from a worktree file."""
        if not question(self,
                'Destroy Local Changes?',
                'This operation will drop uncommitted changes.\n'
                'Continue?', default=False):
            return
        self.process_diff_selection(staged=False, apply_to_worktree=True,
                                    reverse=True)

    def undo_selection(self):
        """Destructively check out content for the selected file from $head."""
        if not question(self,
                'Destroy Local Changes?',
                'This operation will drop uncommitted changes.\nContinue?',
                default=False):
            return
        self.process_diff_selection(staged=False, apply_to_worktree=True,
                                    reverse=True, selected=True)

    def process_diff_selection(self, selected=False,
                               staged=True, apply_to_worktree=False,
                               reverse=False):
        """Implement un/staging of selected lines or hunks."""
        offset, selection = self.offset_and_selection()
        cola.notifier().broadcast(signals.apply_diff_selection,
                                  staged,
                                  selected,
                                  offset,
                                  selection,
                                  apply_to_worktree)
