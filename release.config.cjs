const config = require("@nicxe/semantic-release-config")({
  componentDir: "custom_components/dew_point",
  manifestPath: "custom_components/dew_point/manifest.json",
  projectName: "Dew Point",
  repoSlug: "Nicxe/Home-Assistant-Dew-Point"
}
);

const githubPlugin = config.plugins.find(
  (plugin) => Array.isArray(plugin) && plugin[0] === "@semantic-release/github"
);

if (githubPlugin?.[1]) {
  githubPlugin[1].successCommentCondition = false;
}

module.exports = config;
