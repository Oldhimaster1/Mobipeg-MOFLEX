import config from "./upgrade.config.mjs";

export default {
  ...config,
  testMatch: ["vidinjector-auto.spec.mjs"],
  use: { ...config.use, ignoreHTTPSErrors: true },
};
