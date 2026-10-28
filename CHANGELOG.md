## [0.1.2] - 2026-10-28

### 🚜 Refactor

- *(flow)* Split TextualMessage out of BaseMessage
- *(filter)* Rename NeuroFilter and SparseFilter to *TextualFilter

### 📚 Documentation

- Sync README and docs site with the message model changes

### 🧪 Testing

- Align suites with the message model split and filter renames

### ⚙️ Miscellaneous Tasks

- *(deps)* Bump locked openai, httpcore2 and httpx2
- Update dependencies and upgrade to v0.1.2
## [0.1.1] - 2026-10-20

### 🚀 Features

- *(handler)* Add the MessageHandleFailure failure envelope

### 🐛 Bug Fixes

- *(client)* Make failure handling follow the scope of the fault

### 🚜 Refactor

- *(client)* Drop the reserved handle_concurrency config field

### 📚 Documentation

- Update changelog
- Sync the failure-handling contract across readme and guides
- Describe sequential handling and drop handle_concurrency mentions

### ⚙️ Miscellaneous Tasks

- Upgade to v0.1.1
## [0.1.0] - 2026-10-17

### 🚀 Features

- Base constructions
- Message flowing within timeout ignore
- Base task handler protocols
- Base filters protocols
- Bitongue client and config
- Add api docstrings for public objects
- *(filter)* Add keyword and sparse duplicate-detection filters
- [**breaking**] Require ids on messages and results and rename data modules
- *(client)* Run the filter chain concurrently and make lifecycle idempotent
- *(filter)* Skip non-text messages in the keyword and sparse filters
- *(filter)* Add the neuro filter with LLM-based rule judgment

### 🚜 Refactor

- *(filter)* Trim root re-exports and move JiebaTokenizer to sparse

### 📚 Documentation

- Changelog doc
- Add bilingual readme and contributing guides
- Build bilingual sphinx site with guide pages and api reference
- License mod
- Enable napoleon to render google-style docstrings
- Cover the built-in filters across the bilingual docs site
- Sync the bilingual site and READMEs with ids, concurrency, and the sparse split
- Document the neuro filter across the bilingual site and READMEs

### 🧪 Testing

- Add unit tests mirroring src layout
- Add end-to-end integration tests
- *(filter)* Add unit and integration tests for the filter package
- *(filter)* Add unit and integration tests for the neuro filter

### 📦 Build System

- Make sparse filter dependencies optional
- Add the PyPI publish workflow with trusted publishing

### ⚙️ Miscellaneous Tasks

- Github workflows
