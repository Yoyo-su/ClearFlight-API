// A minimal runtime schema for the v1 API. The TypeScript types in types.ts
// are derived from these schemas, the client validates every response with
// them, and the contract test validates every recorded fixture with them, so
// a field's name, type, nullability or allowed values can't drift between
// the backend models, the fixtures and the frontend (spec §10, D-008).

export type Schema<T> = { check: (value: unknown, path: string) => string | null; _type?: T };
export type Infer<S> = S extends Schema<infer T> ? T : never;

const fail = (path: string, expected: string, value: unknown) =>
  `${path}: expected ${expected}, got ${value === null ? "null" : Array.isArray(value) ? "array" : typeof value}`;

export const str: Schema<string> = {
  check: (v, p) => (typeof v === "string" ? null : fail(p, "string", v)),
};

export const num: Schema<number> = {
  check: (v, p) => (typeof v === "number" && Number.isFinite(v) ? null : fail(p, "number", v)),
};

export const bool: Schema<boolean> = {
  check: (v, p) => (typeof v === "boolean" ? null : fail(p, "boolean", v)),
};

/** An ISO 8601 timestamp string. */
export const datetime: Schema<string> = {
  check: (v, p) =>
    typeof v === "string" && !Number.isNaN(Date.parse(v)) ? null : fail(p, "ISO timestamp", v),
};

export function literal<const T extends string>(...values: T[]): Schema<T> {
  return {
    check: (v, p) =>
      typeof v === "string" && (values as string[]).includes(v) ? null : fail(p, values.join(" | "), v),
  };
}

export function nullable<T>(inner: Schema<T>): Schema<T | null> {
  return { check: (v, p) => (v === null ? null : inner.check(v, p)) };
}

export function arr<T>(inner: Schema<T>): Schema<T[]> {
  return {
    check: (v, p) => {
      if (!Array.isArray(v)) return fail(p, "array", v);
      for (let i = 0; i < v.length; i++) {
        const error = inner.check(v[i], `${p}[${i}]`);
        if (error) return error;
      }
      return null;
    },
  };
}

export function oneOf<A, B>(a: Schema<A>, b: Schema<B>): Schema<A | B> {
  return { check: (v, p) => (a.check(v, p) === null || b.check(v, p) === null ? null : a.check(v, p)) };
}

type Shape = Record<string, Schema<unknown>>;
type FromShape<S extends Shape> = { [K in keyof S]: Infer<S[K]> };

/** An object with exactly these fields (no extra, none missing). */
export function obj<S extends Shape>(shape: S): Schema<FromShape<S>> & { shape: S } {
  return {
    shape,
    check: (v, p) => {
      if (typeof v !== "object" || v === null || Array.isArray(v)) return fail(p, "object", v);
      const record = v as Record<string, unknown>;
      for (const key of Object.keys(record)) {
        if (!(key in shape)) return `${p}.${key}: unexpected field`;
      }
      for (const [key, schema] of Object.entries(shape)) {
        if (!(key in record)) return `${p}.${key}: missing field`;
        const error = schema.check(record[key], `${p}.${key}`);
        if (error) return error;
      }
      return null;
    },
  };
}

/** Adds a cross-field rule; `rule` returns an error message, or null when valid. */
export function refine<T>(inner: Schema<T>, rule: (value: T) => string | null): Schema<T> {
  return {
    check: (v, p) => {
      const error = inner.check(v, p);
      if (error) return error;
      const broken = rule(v as T);
      return broken ? `${p}: ${broken}` : null;
    },
  };
}

/** Throws a readable error when `value` doesn't match `schema`. */
export function validate<T>(schema: Schema<T>, value: unknown, name = "response"): T {
  const error = schema.check(value, name);
  if (error) throw new SchemaError(error);
  return value as T;
}

export class SchemaError extends Error {
  name = "SchemaError";
}
