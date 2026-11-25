// Renders backend-sanitized source HTML inside a locked-down iframe.
//
// The backend removes scripts, inline handlers, and off-origin resources. The empty sandbox is
// still mandatory defence in depth: it grants no scripting, same-origin, form, navigation, or
// popup capabilities. Source HTML never enters the workspace DOM through dangerouslySetInnerHTML.

interface SafeSourceFrameProps {
  html?: string;
  src?: string;
  title: string;
}

export function SafeSourceFrame({ html, src, title }: SafeSourceFrameProps) {
  return (
    <iframe
      className="source-frame"
      title={title}
      sandbox=""
      src={src}
      srcDoc={src ? undefined : html}
      referrerPolicy="no-referrer"
    />
  );
}
