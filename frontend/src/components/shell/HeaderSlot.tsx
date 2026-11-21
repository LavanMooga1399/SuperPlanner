/**
 * The global header has one slot for area-specific tools (plant switcher, assistant, notifications). An area
 * layout renders `<HeaderTools>` and its children are portalled into the header, so they live inside the
 * area's providers (e.g. Manufacturing access) but appear in the one consistent header.
 */
import { createContext, useContext, type ReactNode } from "react";
import { createPortal } from "react-dom";

export const HeaderSlotContext = createContext<HTMLElement | null>(null);

export function HeaderTools({ children }: { children: ReactNode }) {
  const el = useContext(HeaderSlotContext);
  return el ? createPortal(children, el) : null;
}
