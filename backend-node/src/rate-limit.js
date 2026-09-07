import { RateLimitBucket } from "./models.js";
import { config } from "./config.js";

function windowFor(kind, now = Date.now()) {
  const size = kind === "day" ? 24 * 60 * 60 * 1000 : 60 * 1000;
  const timestamp = now instanceof Date ? now.getTime() : now;
  const start = Math.floor(timestamp / size) * size;
  return { start: new Date(start), expiresAt: new Date(start + size + 24 * 60 * 60 * 1000) };
}

async function changeBucket({ key, kind, inputTokens = 0, outputTokens = 0, reservedTokens = 0, requestCount = 0, release = false, session, now = Date.now() }) {
  const { start, expiresAt } = windowFor(kind, now);
  const id = `${key}:${kind}:${start.toISOString()}`;
  const inc = release
    ? { reservedTokens: -reservedTokens }
    : { inputTokens, outputTokens, reservedTokens, requestCount };
  const requestLimit = kind === "day"
    ? []
    : [{ $lte: [{ $add: [{ $ifNull: ["$requestCount", 0] }, requestCount] }, config.requestLimitPerMinute] }];
  try {
    if (release) {
      return await RateLimitBucket.findOneAndUpdate(
        { _id: id },
        { $inc: inc },
        { new: true, session },
      );
    }

    // MongoDB does not allow $expr in an upsert predicate. Create the bucket
    // with a simple _id upsert first, then apply the quota predicate in a
    // second atomic update. The predicate is re-evaluated after every update,
    // so concurrent requests cannot overspend the bucket.
    try {
      await RateLimitBucket.updateOne(
        { _id: id },
        { $setOnInsert: { key, kind, windowStart: start, expiresAt } },
        { upsert: true, setDefaultsOnInsert: true, session },
      );
    } catch (error) {
      // Another request may create the same bucket between the two operations.
      // The subsequent conditional update can safely continue in that case.
      if (error?.code !== 11000) throw error;
    }

    return await RateLimitBucket.findOneAndUpdate(
      {
        _id: id,
        $expr: {
          $and: [
            { $lte: [{ $add: [{ $ifNull: ["$inputTokens", 0] }, { $ifNull: ["$outputTokens", 0] }, { $ifNull: ["$reservedTokens", 0] }, inputTokens + reservedTokens] }, kind === "day" ? config.tokenLimitPerDay : config.tokenLimitPerMinute] },
            ...requestLimit,
          ],
        },
      },
      { $inc: inc },
      { new: true, session },
    );
  } catch (error) {
    // An exhausted bucket can lose the conditional race to another request;
    // MongoDB then reports duplicate _id on the upsert. Treat that as a clean
    // rate-limit rejection rather than leaking a 500 to the client.
    if (error?.code === 11000 && !release) return null;
    throw error;
  }
}

export async function reserveQuota(userId, inputTokens) {
  const now = Date.now();
  const reservation = Math.max(0, config.maxReservedOutputTokens);
  const minute = await changeBucket({ key: `user:${userId}`, kind: "minute", inputTokens, reservedTokens: reservation, requestCount: 1, now });
  if (!minute) return { allowed: false };
  let day;
  try {
    day = await changeBucket({ key: `user:${userId}`, kind: "day", inputTokens, reservedTokens: reservation, requestCount: 1, now });
  } catch (error) {
    await changeBucket({ key: `user:${userId}`, kind: "minute", reservedTokens: reservation, release: true, now });
    await RateLimitBucket.updateOne({ _id: minute._id }, { $inc: { inputTokens: -inputTokens, requestCount: -1 } });
    throw error;
  }
  if (!day) {
    await changeBucket({ key: `user:${userId}`, kind: "minute", reservedTokens: reservation, release: true, now });
    await RateLimitBucket.updateOne({ _id: minute._id }, { $inc: { inputTokens: -inputTokens, requestCount: -1 } });
    return { allowed: false };
  }
  return { allowed: true, reservedTokens: reservation };
}

export async function finalizeQuota(userId, inputTokens, reservedTokens, outputTokens, session, reservedAt = new Date()) {
  for (const kind of ["minute", "day"]) {
    const { start } = windowFor(kind, reservedAt);
    const id = `user:${userId}:${kind}:${start.toISOString()}`;
    await RateLimitBucket.updateOne(
      { _id: id },
      { $inc: { outputTokens, reservedTokens: -reservedTokens } },
      { session },
    );
  }
}

export async function releaseQuota(userId, inputTokens, reservedTokens, reservedAt = new Date()) {
  for (const kind of ["minute", "day"]) {
    const { start } = windowFor(kind, reservedAt);
    await RateLimitBucket.updateOne(
      { _id: `user:${userId}:${kind}:${start.toISOString()}` },
      { $inc: { inputTokens: -inputTokens, reservedTokens: -reservedTokens, requestCount: -1 } },
    );
  }
}

export function quotaHeaders(res, usage) {
  res.set("X-Input-Tokens", String(usage.inputTokens));
  res.set("X-Output-Tokens", String(usage.outputTokens));
  res.set("X-Total-Tokens", String(usage.totalTokens));
}
