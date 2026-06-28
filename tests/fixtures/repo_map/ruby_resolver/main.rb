# A small Ruby app exercising the require/require_relative resolution rules.
require_relative "models/user"   # relative to this file -> models/user.rb
require "helper"                  # load-path (lib/) -> lib/helper.rb
require "json"                    # stdlib/gem -> dropped (no repo file)

def boot
  # Lazy (method-local) require -> medium confidence downstream.
  require_relative "lib/util"
end
