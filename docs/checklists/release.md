# Release checklist

- [ ] All phase gates in the Test Plan met for this release
- [ ] Golden eval (large model) on held-out clips: F1 at or above target, report linked
- [ ] Performance run on target Mac: 3-min clip ~1 min, peak RAM under limit
- [ ] Fault-injection suite green
- [ ] E2E (real model) green on Mac; axe scan has no serious issues
- [ ] Listening checklist passed on 3 rendered clips
- [ ] CHANGELOG.md updated; version bumped (SemVer); tag pushed
- [ ] Jira tasks for this release closed
