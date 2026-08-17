# fleet-monitor

[![CI](https://github.com/julianAO2002/fleet-monitor/actions/workflows/ci.yml/badge.svg)](https://github.com/julianAO2002/fleet-monitor/actions/workflows/ci.yml)

A deployment laboratory for fleets of remote nodes with intermittent
connectivity: vessels report to a central API, which derives their status from
how long they have been silent.

Architecture, setup and technical decisions are documented below as the project
is built.

[`deploy/README.md`](deploy/README.md) describes how this would reach a real
fleet of two hundred vessels, and states plainly which parts are implemented
and which are design.
