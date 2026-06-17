"use client";

import type { FC } from "react";
import type { SyntaxHighlighterProps } from "@assistant-ui/react-markdown";

// Plain-code fallback — no syntax highlighting. Replace with a shiki-based
// implementation (e.g. npx assistant-ui add shiki-highlighter) when needed.
export const SyntaxHighlighter: FC<SyntaxHighlighterProps> = ({
  components: { Pre, Code },
  code,
  language,
}) => (
  <Pre>
    <Code className={language ? `language-${language}` : undefined}>
      {code}
    </Code>
  </Pre>
);
