from __future__ import annotations

from pulse.history.status_labels import status_color, status_tint
from pulse.tui.history_theme import HISTORY_CSS
from pulse.tui.home_theme import HOME_CSS
from pulse.tui.palette import (
    BG,
    BG_PANEL,
    BORDER,
    ERROR,
    ERROR_SOFT,
    LIME,
    LIME_MUTED,
    RAISED,
    TEXT,
    TEXT_MUTED,
)
from pulse.tui.settings_theme import SETTINGS_CSS

AWAITING = status_color("awaiting_input")
AWAITING_TINT = status_tint("awaiting_input")

COCKPIT_CSS = (
    f"""
Screen {{
    background: {BG};
    color: {TEXT};
}}

AppHeader {{
    dock: top;
    height: 3;
    layout: vertical;
    background: {BG_PANEL};
    color: {TEXT_MUTED};
    border-bottom: solid {BORDER};
    padding: 0 1;
}}

#cockpit-body {{
    height: 1fr;
    width: 100%;
    layout: horizontal;
}}

AppHeader #header-top,
AppHeader #header-sub {{
    width: 100%;
    height: 1;
}}

AppHeader .brand {{
    color: {LIME};
    text-style: bold;
    width: auto;
    padding-right: 2;
}}

AppHeader .workflow-label {{
    color: {TEXT};
    text-style: bold;
    width: 1fr;
    overflow: hidden;
}}

AppHeader .run-badge {{
    width: auto;
    margin-right: 1;
}}

AppHeader .run-clock {{
    width: auto;
    background: {RAISED};
}}

AppHeader .run-meter {{
    width: auto;
    padding-right: 1;
}}

AppHeader .run-status {{
    color: {TEXT};
    width: 1fr;
    overflow: hidden;
}}

AppHeader .run-where {{
    color: {TEXT_MUTED};
    width: auto;
    text-align: right;
}}

PhaseSidebar {{
    width: 32%;
    min-width: 28;
    height: 100%;
    background: {BG};
    border-right: solid {BORDER};
    padding: 1 1;
    overflow-y: auto;
}}

PhaseSidebar #phase-content {{
    width: 100%;
    height: auto;
}}

LogStream {{
    width: 1fr;
    height: 100%;
    background: {BG};
    padding: 0 1;
    layout: vertical;
}}

LogStream #stream-header {{
    height: 1;
}}

LogStream #stream-meta {{
    height: 1;
    margin-bottom: 1;
}}

LogStream #stream-body {{
    height: 1fr;
    scrollbar-color: {LIME_MUTED};
}}

LogStream #stream-content {{
    width: 100%;
    height: auto;
}}

LogStream #prompt-slot {{
    width: 100%;
    height: auto;
    max-height: 70%;
}}

LogStream .stream-title {{
    color: {LIME};
    text-style: bold;
}}

LogStream .stream-meta {{
    color: {TEXT_MUTED};
}}

ArtifactPane {{
    width: 42%;
    min-width: 36;
    height: 100%;
    background: {BG};
    border-left: solid {BORDER};
    padding: 1 0 0 0;
    layout: vertical;
}}

ArtifactPane.-collapsed {{
    width: 8;
    min-width: 8;
    padding: 1 0;
}}

#cockpit-body.artifacts-open PhaseSidebar {{
    width: 22%;
    min-width: 20;
}}

ArtifactPane:focus {{
    border-left: solid {LIME};
}}

ArtifactPane #artifact-open {{
    display: none;
    width: 100%;
    height: 1fr;
    color: {LIME};
    text-align: center;
    content-align: center top;
    padding: 1 0;
}}

ArtifactPane.-collapsed #artifact-open {{
    display: block;
}}

ArtifactPane #artifact-title-row {{
    height: 1;
    width: 100%;
    padding: 0 1;
}}

ArtifactPane #artifact-header {{
    width: 1fr;
    height: 1;
    color: {LIME};
    text-style: bold;
}}

ArtifactPane #artifact-close {{
    width: 3;
    height: 1;
    content-align: right middle;
    color: {TEXT_MUTED};
}}

ArtifactPane #artifact-close:hover {{
    color: {LIME};
}}

ArtifactPane #artifact-meta {{
    height: 1;
    padding: 0 1;
    color: {TEXT_MUTED};
    margin-bottom: 1;
}}

ArtifactPane #artifact-tabs {{
    height: 1;
    width: 100%;
    padding: 0 1;
    overflow-x: auto;
}}

ArtifactPane .artifact-tab {{
    width: auto;
    height: 1;
    color: {TEXT_MUTED};
}}

ArtifactPane .artifact-tab.-active {{
    color: {LIME};
    text-style: bold;
}}

ArtifactPane #artifact-body {{
    height: 1fr;
    scrollbar-color: {LIME_MUTED};
}}

ArtifactPane Markdown {{
    height: auto;
    margin: 0;
    padding: 0 1 1 1;
    background: {BG};
}}

AppFooter {{
    dock: bottom;
    height: 1;
    background: {BG_PANEL};
    color: {TEXT_MUTED};
    padding: 0 1;
}}

AppFooter .key {{
    color: {LIME};
}}

OnboardingScreen {{
    background: {BG};
    align: center middle;
}}

OnboardingScreen #onboard-content {{
    width: 80%;
    max-width: 90;
    height: auto;
    align: center middle;
}}

OnboardingScreen .onboard-title {{
    width: 100%;
    color: {LIME};
    text-style: bold;
    text-align: center;
    margin-bottom: 1;
}}

OnboardingScreen .onboard-hint {{
    width: 100%;
    color: {TEXT_MUTED};
    text-align: center;
    margin-bottom: 1;
}}

OnboardingScreen OptionList {{
    width: 100%;
    height: auto;
    max-height: 18;
    background: {BG_PANEL};
    border: solid {BORDER};
    color: {TEXT};
}}

OnboardingScreen OptionList:focus {{
    border: solid {LIME};
}}

OnboardingScreen .onboard-report {{
    width: 100%;
    color: {TEXT_MUTED};
    text-align: left;
    margin-top: 1;
    height: auto;
    max-height: 12;
}}

OnboardingScreen #onboard-input {{
    width: 100%;
    margin-top: 1;
    background: {BG_PANEL};
    border: solid {BORDER};
    color: {TEXT};
}}

OnboardingScreen #onboard-input:focus {{
    border: solid {LIME};
}}

OnboardingScreen .onboard-hint-keys {{
    width: 100%;
    color: {TEXT_MUTED};
    text-align: center;
    margin-top: 1;
}}

PromptDock {{
    width: 100%;
    height: 100%;
    layout: vertical;
    background: {BG_PANEL};
    border-top: heavy {AWAITING};
    padding: 0 1;
}}

PromptDock .prompt-title {{
    color: {AWAITING};
    text-style: bold;
    height: 1;
}}

PromptDock .prompt-text {{
    color: {TEXT};
    height: auto;
}}

PromptDock .prompt-hint {{
    color: {TEXT_MUTED};
    height: 1;
}}

PromptDock OptionList {{
    width: 100%;
    color: {TEXT};
    background: {BG_PANEL};
    border: none;
    padding: 0 1;
}}

PromptDock OptionList:focus {{
    border: none;
}}

PromptDock OptionList > .option-list--option-highlighted,
PromptDock OptionList:focus > .option-list--option-highlighted {{
    background: {AWAITING_TINT};
    color: {AWAITING};
    text-style: bold;
}}

PromptDock Input {{
    margin: 0;
}}

PromptDock #prompt-actions {{
    height: 3;
    width: 100%;
}}

ResumeChoiceScreen {{
    align: center middle;
}}

ResumeChoiceScreen #resume-box {{
    width: 62;
    height: auto;
    padding: 1 2;
    background: {BG_PANEL};
    border: solid {LIME};
}}

ResumeChoiceScreen .resume-title {{
    color: {LIME};
    text-style: bold;
    width: 100%;
}}

ResumeChoiceScreen .resume-slug {{
    color: {TEXT};
    width: 100%;
}}

ResumeChoiceScreen .resume-summary {{
    color: {TEXT_MUTED};
    width: 100%;
    margin-bottom: 1;
}}

ResumeChoiceScreen OptionList {{
    width: 100%;
    height: auto;
    background: {BG_PANEL};
    border: none;
    color: {TEXT};
}}

ResumeChoiceScreen OptionList:focus {{
    border: none;
}}

ResumeChoiceScreen OptionList > .option-list--option-highlighted,
ResumeChoiceScreen OptionList:focus > .option-list--option-highlighted {{
    background: {LIME_MUTED};
    color: {TEXT};
    text-style: bold;
}}

ResumeChoiceScreen .resume-hint {{
    color: {TEXT_MUTED};
    width: 100%;
    margin-top: 1;
}}

ConfirmScreen {{
    align: center middle;
}}

ConfirmScreen #confirm-box {{
    width: 62;
    height: auto;
    padding: 1 2;
    background: {BG_PANEL};
    border: solid {ERROR};
}}

ConfirmScreen .confirm-title {{
    color: {ERROR_SOFT};
    text-style: bold;
    width: 100%;
}}

ConfirmScreen .confirm-detail {{
    color: {TEXT_MUTED};
    width: 100%;
    margin-bottom: 1;
}}

ConfirmScreen OptionList {{
    width: 100%;
    height: auto;
    background: {BG_PANEL};
    border: none;
    color: {TEXT};
}}

ConfirmScreen OptionList:focus {{
    border: none;
}}

ConfirmScreen OptionList > .option-list--option-highlighted,
ConfirmScreen OptionList:focus > .option-list--option-highlighted {{
    background: {LIME_MUTED};
    color: {TEXT};
    text-style: bold;
}}

ConfirmScreen .confirm-hint {{
    color: {TEXT_MUTED};
    width: 100%;
    margin-top: 1;
}}

BranchNameScreen {{
    align: center middle;
}}

BranchNameScreen #branch-box {{
    width: 62;
    height: auto;
    padding: 1 2;
    background: {BG_PANEL};
    border: solid {LIME};
}}

BranchNameScreen .branch-title {{
    color: {LIME};
    text-style: bold;
    width: 100%;
}}

BranchNameScreen Input {{
    margin: 1 0;
}}

BranchNameScreen OptionList {{
    width: 100%;
    height: auto;
    background: {BG_PANEL};
    border: none;
    color: {TEXT};
}}

BranchNameScreen OptionList:focus {{
    border: none;
}}

BranchNameScreen .branch-hint {{
    color: {TEXT_MUTED};
    width: 100%;
    margin-top: 1;
}}
"""
    + HOME_CSS
    + HISTORY_CSS
    + SETTINGS_CSS
)
