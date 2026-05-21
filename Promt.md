AI Development Task — Telegram Bot + Web App Improvements + GitHub Auto Deploy

You need to modify and improve the existing Telegram bot and web application project.

IMPORTANT:

Do NOT remove functionality.
Do NOT simplify features.
Do NOT reduce code quality or visual quality.
Preserve the entire existing functionality and interface.
Your task is ONLY to improve, optimize, fix, and refine the project.
The final result must remain visually and functionally equivalent or better than the current version.

The project directory is located at:

C:\Users\USER\Desktop\Qwen 3.6 Plus\tg-bot
1. Create Automatic GitHub Upload .EXE Tool

Create an .exe file that, when double-clicked:

Automatically uploads ALL changed project files from:
C:\Users\USER\Desktop\Qwen 3.6 Plus\tg-bot

to my PRIVATE GitHub repository.

Requirements:

The upload process must happen automatically after double-clicking the .exe.
The tool must:
detect changed files,
commit changes,
push them to my private GitHub repository.
Excluded files:
DEPLOY_GUIDE.md
CONFIG_GUIDE.txt
Everything else inside the project must be uploaded.

The upload process should behave like a one-click deploy/update system.

Additionally:

Create detailed instructions explaining:
how to connect my private GitHub repository,
how to authorize GitHub access,
how to configure Git,
how to set repository URL,
how to use GitHub tokens if required,
how to build/use the .exe.

The instructions must be beginner-friendly and step-by-step.

2. Fix and Improve the Web App

The web app currently has multiple UI and responsiveness issues.

You must fully fix and optimize the frontend so it works correctly on BOTH:

mobile devices,
desktop PCs.
Responsive Layout

Requirements:

The interface must properly adapt to all screen sizes.
The site must scale correctly for:
phones,
tablets,
laptops,
desktop monitors.
Fix all broken responsive behavior.
Prevent UI overflow issues.
Ensure elements never leave the visible viewport.
Critical Mobile Bug — Infinite Horizontal Scrolling

Current issue:

When opening the web app from the Telegram bot on mobile,
the user can infinitely scroll horizontally to the right.
UI elements disappear while scrolling.

Fix this completely.

Requirements:

Remove all horizontal overflow.
Prevent infinite sideways scrolling.
Ensure the page width never exceeds viewport width.
All elements must remain visible and correctly positioned.
Carousel Images Not Displaying

Current issue:

Images that should appear inside the carousel do not display.
The images are stored inside the GitHub project repository.

Fix this issue completely.

Requirements:

Ensure carousel images load correctly.
Fix all broken paths/imports/static asset handling.
Ensure images work in production deployment.
Add Swipe / Drag Carousel Controls

Improve carousel interaction.

On mobile:
User must be able to swipe:
left,
right,
with finger gestures.
On desktop:
User must be able to:
hold mouse button on image,
drag left/right,
move carousel naturally.

The carousel should feel smooth and modern.

Top Scroll Progress Bar Bug

Current issue:

On mobile, the top progress/menu scroll indicator behaves incorrectly.
Sometimes it disappears completely.
Sometimes it does not update.

Fix this.

Requirements:

The top progress indicator must:
always stay visible,
update correctly while scrolling,
work smoothly on mobile Telegram Web App,
never randomly disappear.
3. Fix Telegram Bot Text Encoding and UI

The Telegram bot currently sends broken formatted messages like:

f44b Добро пожаловать!\n\nЭто бот для получения доступа...

Problems include:

random symbols like f44b,
broken unicode,
visible \n\n,
formatting issues.

Fix ALL message formatting issues.

Requirements:

Proper emoji rendering,
Proper UTF-8 encoding,
Proper line breaks,
Clean Russian-language formatting,
No broken escape sequences visible to users.
Merge Duplicate Buttons

Current issue:

The bot currently has TWO separate buttons:

"Ознакомиться со скриптом"
"Приобрести скрипт"

But both buttons open the SAME website.

Fix this by merging them into ONE button:

Ознакомиться/купить скрипт

Requirements:

Entire interface must remain in Russian.
Remove duplicate navigation logic.
Ensure button works correctly.
4. Fix Telegram Admin Panel (/adm)

Current issue:

The admin panel visually appears to work,
but backend functionality freezes.

Examples:

token creation freezes,
tariff price changes freeze,
admin actions never complete.

Fix the admin panel completely.

Requirements:

Fully debug admin action handlers.
Fix backend state handling.
Fix async logic if broken.
Ensure all admin actions execute successfully.
Ensure no hanging/freezing occurs.
Validate:
token creation,
tariff editing,
saving settings,
admin commands,
database updates,
callback handling.

The admin panel must become fully functional and stable.

5. Improve Back Navigation in Telegram Bot

Current issue:

When pressing “Back” buttons,
the bot sends NEW messages instead of updating the existing message.

Fix this behavior.

Requirements:

The bot must edit the existing message instead of sending a new one.
Replace:
text,
buttons,
menus
inside the SAME Telegram message.

This should create a cleaner and more professional UI experience.

Use:

message editing,
inline keyboard updates,
callback editing,
instead of sending new messages.
6. Optimize the Bot and Website for Low-Resource Hosting

The project may run on free hosting plans with limited resources.

You must optimize the project WITHOUT reducing functionality.

IMPORTANT RULES:

Do NOT remove features.
Do NOT reduce visual quality.
Do NOT simplify logic.
Do NOT break functionality.
Do NOT rewrite everything into a minimal version.

You are ONLY allowed to:

optimize performance,
reduce unnecessary resource usage,
improve efficiency,
improve loading speed,
improve memory usage,
improve rendering performance,
optimize database queries,
optimize frontend rendering,
optimize API usage,
optimize Telegram bot event handling.

The final product must:

look the same or better,
work the same or better,
consume fewer resources,
perform smoother on low-resource hosting.
General Development Requirements
Preserve existing project architecture whenever possible.
Maintain compatibility with Telegram Web Apps.
Ensure production-ready stability.
Avoid introducing breaking changes.
Write clean and maintainable code.
Add comments where necessary.
Verify all fixes work on:
desktop,
Android,
iPhone,
Telegram in-app browser.

Before finalizing:

thoroughly test all functionality,
verify responsiveness,
verify admin panel actions,
verify GitHub auto-upload system,
verify carousel interactions,
verify message editing behavior,
verify image loading,
verify mobile rendering.

The final result must feel polished, modern, stable, and production-ready.