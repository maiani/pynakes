/** Said when a write was refused because the file moved under its approved preview. */
export const FILE_MOVED_MESSAGE =
  "The file changed while this change was awaiting approval, so nothing was written. " +
  "Review the current state and apply again.";

/** Said when the engine's preview carried no digest to make the write conditional on. */
export const NO_FINGERPRINT_MESSAGE =
  "Nothing was written: the engine did not report the file's fingerprint, so the write " +
  "could not be guarded against a concurrent change. Update pynakes or select a compatible engine.";
