/* SF State Template style.js
 * This script will be the default js file to ship with the SF State Template theme.
 */
(function($) {
    Drupal.behaviors.drupaldeveloper = {
        attach: function (context) {

            // Search box action
            $('#search-box').submit(function(){
                var topSearch = $('input[name=top-search]:checked').attr('value');
                var searchString = $('input[name=q]').val();
                if (topSearch == 'global') {
                    $("#search-box").attr("action", "https://google.sfsu.edu/gsearch/" + searchString);
                    $("#search-box").attr("method","post");
                } else {
                    $("#search-box").attr("action", "/search/results");
                    $("#search-box").attr("method","get");
                }

            });
            // End Search box action

            $(window).on("load", function() {
                // Footer position calculation
                if($('.main-container').length) {
                    $(window).on('load resize', function() {
                        /* Get heights of the elements */
                        var headerHeight = $('#header').outerHeight();
                        var siteNameHeight = $('.site-name').outerHeight();
                        var navHeight = $('.main-nav').outerHeight();
                        var footerLocalHeight = $('.footer-local').outerHeight();
                        var footerHeight = $('.footer').outerHeight();
                        var mainHeight = $(window).height() - headerHeight - siteNameHeight - navHeight - footerLocalHeight - footerHeight;
                        // Set min height for Main div and content area
                        $('.main-container').css({"min-height":mainHeight});
                    }).trigger('resize');
                }
                // End Footer position calculation
            });


            // If div has page not found component
            if ($("div").hasClass("pl-component--page-not-found")) {
                // Then add class screen reader tag to heading 1
                $("h1.page-header").addClass("sr-only");
            }
            // End Page Not Found
    }
    }
})(jQuery);
