// 사내 Claude 게이트웨이
const UPSTREAM = "https://api.anthropic.com";
app.use("/v1", (req, res, next) => {
  const key = req.headers["x-api-key"];
  if (!isAllowed(key)) return res.status(401).end();
  next();
});
