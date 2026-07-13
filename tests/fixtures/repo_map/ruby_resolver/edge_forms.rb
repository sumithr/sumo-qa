# Require-statement spelling variants, for the extract() unit tests. None of
# these targets exist in the fixture, so they contribute no orchestrator edges.
puts "loading edge forms"                  # bare non-require method call -> ignored
require 'lib/single_quote'                 # single-quoted string literal
require("paren_form")                      # parenthesised call form
require "a#{ENV['X']}b"                     # string interpolation -> dynamic, dropped
require File.join(__dir__, "computed")     # non-literal argument -> dropped
[1].each { require_relative "blockmod" }   # require nested inside a block (not a method)
