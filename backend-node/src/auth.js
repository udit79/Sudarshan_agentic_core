import crypto from "node:crypto";
import jwt from "jsonwebtoken";
import { OAuth2Client } from "google-auth-library";
import { config } from "./config.js";
import { AuthState, RefreshToken, User } from "./models.js";

const ACCESS_COOKIE = "sudarshan_access";
const REFRESH_COOKIE = "sudarshan_refresh";
const OAUTH_STATE_COOKIE = "sudarshan_oauth_state";

function hash(value) {
  return crypto.createHash("sha256").update(value).digest("hex");
}

function googleClient() {
  if (!config.googleClientId || !config.googleClientSecret || !config.googleCallbackUrl) {
    throw new Error("Google OAuth2 is not configured");
  }
  return new OAuth2Client(config.googleClientId, config.googleClientSecret, config.googleCallbackUrl);
}

function cookieOptions(maxAge) {
  return {
    httpOnly: true,
    secure: config.cookieSecure,
    sameSite: config.cookieSameSite,
    path: "/",
    ...(maxAge ? { maxAge } : {}),
  };
}

function setAuthCookies(res, accessToken, refreshToken) {
  res.cookie(ACCESS_COOKIE, accessToken, cookieOptions(15 * 60 * 1000));
  res.cookie(REFRESH_COOKIE, refreshToken, cookieOptions(30 * 24 * 60 * 60 * 1000));
}

function clearAuthCookies(res) {
  res.clearCookie(ACCESS_COOKIE, cookieOptions());
  res.clearCookie(REFRESH_COOKIE, cookieOptions());
}

function issueAccessToken(user) {
  return jwt.sign(
    { sub: String(user._id), email: user.email, roles: user.roles, type: "access" },
    config.accessSecret,
    { expiresIn: config.accessTtl, issuer: "sudarshan-gateway", audience: "sudarshan-api" },
  );
}

async function issueRefreshToken(user) {
  const jti = crypto.randomUUID();
  const token = jwt.sign(
    { sub: String(user._id), jti, type: "refresh" },
    config.refreshSecret,
    { expiresIn: config.refreshTtl, issuer: "sudarshan-gateway", audience: "sudarshan-api" },
  );
  const decoded = jwt.decode(token);
  await RefreshToken.create({
    tokenHash: hash(token),
    userId: String(user._id),
    jti,
    expiresAt: new Date(decoded.exp * 1000),
  });
  return token;
}

function publicUser(user) {
  return {
    id: String(user._id),
    email: user.email,
    email_verified: user.emailVerified,
    name: user.name,
    picture: user.picture,
    roles: user.roles,
  };
}

export function authMiddleware(req, res, next) {
  const header = req.get("authorization") || "";
  const bearer = header.startsWith("Bearer ") ? header.slice(7).trim() : "";
  const token = bearer || req.cookies?.[ACCESS_COOKIE];
  if (!token) return res.status(401).json({ error: "Authentication required" });
  try {
    const claims = jwt.verify(token, config.accessSecret, {
      issuer: "sudarshan-gateway",
      audience: "sudarshan-api",
    });
    if (typeof claims !== "object" || claims.type !== "access" || !claims.sub) {
      throw new Error("Invalid access token claims");
    }
    req.auth = claims;
    return next();
  } catch {
    return res.status(401).json({ error: "Invalid or expired access token" });
  }
}

export async function startGoogle(req, res, next) {
  try {
    const client = googleClient();
    const state = crypto.randomBytes(32).toString("base64url");
    await AuthState.create({
      _id: hash(state),
      expiresAt: new Date(Date.now() + 10 * 60 * 1000),
      returnTo: config.frontendUrl,
    });
    res.cookie(OAUTH_STATE_COOKIE, state, cookieOptions(10 * 60 * 1000));
    const url = client.generateAuthUrl({
      access_type: "offline",
      prompt: "consent",
      scope: ["openid", "email", "profile"],
      state,
    });
    return res.redirect(url);
  } catch (error) {
    return next(error);
  }
}

export async function googleCallback(req, res, next) {
  try {
    const { code, state, error } = req.query;
    if (error) return res.status(401).json({ error: "Google authentication was denied" });
    if (typeof code !== "string" || typeof state !== "string") {
      return res.status(400).json({ error: "Google callback is missing code or state" });
    }
    if (!req.cookies?.[OAUTH_STATE_COOKIE] || req.cookies[OAUTH_STATE_COOKIE] !== state) {
      return res.status(400).json({ error: "Google OAuth state is not bound to this browser" });
    }
    const stateRecord = await AuthState.findOneAndDelete({ _id: hash(state) });
    if (!stateRecord || stateRecord.expiresAt.getTime() < Date.now()) {
      return res.status(400).json({ error: "Google OAuth state is invalid or expired" });
    }

    const client = googleClient();
    const { tokens } = await client.getToken(code);
    if (!tokens.id_token) return res.status(401).json({ error: "Google did not return an ID token" });
    const ticket = await client.verifyIdToken({ idToken: tokens.id_token, audience: config.googleClientId });
    const profile = ticket.getPayload();
    if (!profile?.sub || !profile.email || profile.email_verified !== true) {
      return res.status(403).json({ error: "A verified Google email is required" });
    }

    const user = await User.findOneAndUpdate(
      { googleSub: profile.sub },
      {
        $set: {
          email: profile.email.toLowerCase(),
          emailVerified: true,
          name: profile.name || profile.email,
          picture: profile.picture || "",
          lastLoginAt: new Date(),
        },
        $setOnInsert: { googleSub: profile.sub, roles: ["user"] },
      },
      { new: true, upsert: true, setDefaultsOnInsert: true },
    );
    const accessToken = issueAccessToken(user);
    const refreshToken = await issueRefreshToken(user);
    setAuthCookies(res, accessToken, refreshToken);
    res.clearCookie(OAUTH_STATE_COOKIE, cookieOptions());

    if (stateRecord.returnTo) return res.redirect(stateRecord.returnTo);
    return res.json({ user: publicUser(user), accessToken });
  } catch (error) {
    return next(error);
  }
}

export async function refreshSession(req, res, next) {
  try {
    const refresh = req.cookies?.[REFRESH_COOKIE];
    if (!refresh) return res.status(401).json({ error: "Refresh token is required" });
    const claims = jwt.verify(refresh, config.refreshSecret, {
      issuer: "sudarshan-gateway",
      audience: "sudarshan-api",
    });
    if (typeof claims !== "object" || claims.type !== "refresh" || !claims.sub || !claims.jti) {
      return res.status(401).json({ error: "Invalid refresh token" });
    }
    const stored = await RefreshToken.findOneAndDelete({ tokenHash: hash(refresh), jti: claims.jti });
    if (!stored) return res.status(401).json({ error: "Refresh token has been revoked or reused" });
    const user = await User.findById(claims.sub);
    if (!user) return res.status(401).json({ error: "User no longer exists" });
    const accessToken = issueAccessToken(user);
    const refreshToken = await issueRefreshToken(user);
    setAuthCookies(res, accessToken, refreshToken);
    return res.json({ user: publicUser(user), accessToken });
  } catch (error) {
    if (error.name === "JsonWebTokenError" || error.name === "TokenExpiredError") {
      return res.status(401).json({ error: "Invalid or expired refresh token" });
    }
    return next(error);
  }
}

export async function currentUser(req, res, next) {
  try {
    const user = await User.findById(req.auth.sub).lean();
    if (!user) return res.status(401).json({ error: "User no longer exists" });
    return res.json({ user: publicUser(user) });
  } catch (error) {
    return next(error);
  }
}

export async function logout(req, res, next) {
  try {
    const refresh = req.cookies?.[REFRESH_COOKIE];
    if (refresh) await RefreshToken.deleteOne({ tokenHash: hash(refresh) });
    clearAuthCookies(res);
    res.clearCookie(OAUTH_STATE_COOKIE, cookieOptions());
    return res.status(204).send();
  } catch (error) {
    return next(error);
  }
}

export { publicUser };
