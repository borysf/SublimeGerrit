# SublimeGerrit
The full-featured Gerrit Code Review integration for **Sublime Text 3 (will not work in Sublime Text 2)**


## Installation
### via Git clone
Clone this repo into Sublime Text's Packages directory. Target directory name **must** be SublimeGerrit.


## Setup
1. Open Command Palette
2. Search for "Gerrit: Basic Setup"
3. Select "General > Connection"
4. Type your connection details. Host name must be in form: http(s)://host:port[/path]
5. Back to Basic Setup and select "General > Git"
6. Configure your Git settings


## Advanced setup
More advanced settings can be changed via "Preferences > Package Settings > SublimeGerrit - User". Please also take a look at "Preferences > Package Settings > SublimeGerrit - Default" for all accessible settings.


## Usage

1. Press [ctrl] + [alt] + [g] or select "Gerrit: Basic Setup" command from Command Palette.
2. Configure connection settings.
   When you're done, use [ctrl] + [alt] + [g] or "Gerrit" command from Command Palette to show
   the list of available commands for current view.

3. All commands that are accessible after pressing [ctrl] + [alt] + [g] are also available
   in Sublime's Command Palette.

4. You can also use the following keyboard shortcuts to work faster:

      [ctrl] + [alt] + [g] - display available Gerrit commands for current view

  Change view:
  
      [d]              - download commands 
      [ctrl] + [d]     - revert checkout 
      [p]              - switch Patch Set 
      [enter]          - review change 
      [r]              - rebase change 
      [a]              - abandon change 
      [alt] + [a]      - restore abandoned change 
      [u]              - publish draft change 
      [q]              - delete draft change 
      [m]              - edit commit message 
      [t]              - edit topic 
      [c]              - cherry pick change 
      [F5]             - refresh view 
      [f]              - menu of changed files 
      [ctrl] + [a]     - add reviewer 
      [ctrl] + [r]     - remove reviewer 


  Diff view:
  
      [up]             - go to previous change 
      [down]           - go to next change 
      [left]           - load previous file 
      [right]          - load next file 
      [alt] + [up]     - show previous comment 
      [alt] + [down]   - show next comment 
      [i]              - toggle intraline differences 
      [b]              - menu to change base patch set 
      [c]              - menu to navigate through comments 
      [d]              - menu to navigate through draft comments 
      [f]              - menu to navigate through changed files 
      [e]              - menu to list changes in file 


## Note
Previously the project was a closed-source and required license purchase for continued use. Because it was not very popular, I decided to publish it freely. Anyway, I'd like to thank these few great people who decided to support me by purchasing a license! :)


## Ad ;)
Missing side-by-side diff in Sublime Text? Take a look at my project: [Sublimerge - the professional diff and merge tool for Sublime Text](http://www.sublimerge.com)
