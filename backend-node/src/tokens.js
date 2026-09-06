import { encodingForModel, getEncoding } from "js-tiktoken";

let encoder;
try {
  encoder = encodingForModel("gpt-4o-mini");
} catch {
  encoder = getEncoding("cl100k_base");
}

export function countTokens(value) {
  const text = typeof value === "string" ? value : JSON.stringify(value ?? "");
  return encoder.encode(text).length;
}

export function countResultTokens(result) {
  return countTokens(result || {});
}
