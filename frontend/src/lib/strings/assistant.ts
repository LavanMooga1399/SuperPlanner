/**
 * Assistant copy (UX-STANDARD 8, i18n readiness): page headers, buttons, labels, empty states, dialogs and toasts,
 * keyed per screen (`assistant.<screen>.<kind>.<name>`). English is the default; `lib/i18n.ts` merges this map into
 * the dictionary, so a translation replaces values only.
 */
export const assistantStrings = {
  "assistant.assistantPanel.aria.assistant": "Assistant",
  "assistant.assistantPanel.aria.closeTheAssistant": "Close the assistant",
  "assistant.assistantPanel.aria.conversation": "Conversation",
  "assistant.assistantPanel.btn.answersMayBeWrongCheck": "Answers may be wrong; check the linked records.",
  "assistant.assistantPanel.btn.beforeYouAsk": "Before you ask",
  "assistant.assistantPanel.btn.checkAgain": "Check again",
  "assistant.assistantPanel.btn.earlierConversations": "Earlier conversations",
  "assistant.assistantPanel.btn.iUnderstand": "I understand",
  "assistant.assistantPanel.btn.moreOptions": "More options",
  "assistant.assistantPanel.btn.newConversation": "New conversation",
  "assistant.assistantPanel.btn.stop": "Stop",
  "assistant.assistantPanel.btn.whatChanged": "What changed?",
  "assistant.assistantPanel.btn.whatLimitsThisWeek": "What limits this week?",
  "assistant.assistantPanel.btn.whyLate": "Why late?",
  "assistant.assistantPanel.head.askingInYourOwnWords": "Asking in your own words is not available",
  "assistant.assistantPanel.ph.egWhyIsDokv00310Late": "e.g. Why is DO-KV-003/10 late and what can I do?",
  "assistant.assistantPanel.text.conversationsAreStoredInThis": "Conversations are stored in this plant for 30 days and only you can see them.",
  "assistant.assistantPanel.text.noEarlierConversationsTheyAre": "No earlier conversations. They are kept for 30 days.",
  "assistant.assistantPanel.text.theQuickExplanationsAboveWork": "The quick explanations above work without it.",
  "assistant.draftCardView.btn.applied": "Applied",
  "assistant.draftCardView.btn.applyCreatesAWhatifRun": "Apply creates a what-if run to compare with the plan. It never changes the live plan and cannot be published.",
  "assistant.draftCardView.btn.cancel": "Cancel",
  "assistant.draftCardView.btn.suggestionNotApplied": "Suggestion, not applied",
  "assistant.draftCardView.btn.yesApply": "Yes, apply",
  "assistant.draftCardView.head.showTheExactRequest": "Show the exact request",
} as const;
