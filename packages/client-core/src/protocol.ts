/** UI-to-host payloads shared by adapters. Hosts must still validate requests. */
import type { Mutation } from "./library";

export interface GroupActionRequest {
  name: string;
  /** Referenced by entries but absent from the declared hierarchy. */
  undeclared?: boolean;
  description?: string;
}

export interface ViewMessage {
  type?: string;
  key?: string;
  keys?: string[];
  member?: boolean;
  field?: string;
  value?: string | null;
  /** The value a staged change was made against; null when the field was absent. */
  base?: string | null;
  entryType?: string;
  /** The requested new citation key, for `renameKey`. */
  newKey?: string;
  query?: string;
  where?: string;
  fuzzy?: boolean;
  /** Which search this is, echoed back so a late answer to an older one is ignored. */
  seq?: number;
  /** Absolute path, for `openMaterial` and `openCitation`. */
  path?: string;
  /** Where a material should open, for `openMaterial`; absent means the setting. */
  opener?: string;
  /** One-based position within that file, for `openCitation`. */
  line?: number;
  column?: number;
  /** The entry- or group-level change requested, for `mutate`. */
  mutation?: Mutation;
  /** Group names the view already knows about, for `promptGroup` and the group actions. */
  groups?: string[];
  /** The group node a sidebar action was invoked on, for `groupActions`. */
  group?: GroupActionRequest;
}

/** Presentation state and messaging; a host provides one bridge per view. */
export interface ViewBridge {
  postMessage(message: ViewMessage): void;
  getState(): unknown;
  setState(state: unknown): void;
  onMessage(handler: (message: unknown) => void): () => void;
}
