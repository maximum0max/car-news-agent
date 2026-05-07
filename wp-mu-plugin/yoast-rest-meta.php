<?php
/**
 * Plugin Name: Yoast REST Meta
 * Description: Exposes Yoast SEO post-meta keys (focus keyphrase, meta description,
 *              SEO title) to the WordPress REST API so external clients can set them
 *              when creating posts. Without this, Yoast meta sent via REST is silently
 *              dropped and the SEO score stays red.
 * Author:      car-news-agent
 * Version:     1.0.0
 *
 * Install:
 *   1. Upload this file to wp-content/mu-plugins/yoast-rest-meta.php
 *      (create the mu-plugins folder if it doesn't exist — must-use plugins
 *       auto-load, no activation required)
 *   2. Done. The agent's next post will set the focus keyphrase and Yoast
 *      will compute a real SEO score.
 */

add_action('init', function () {
    $keys = [
        '_yoast_wpseo_focuskw',
        '_yoast_wpseo_metadesc',
        '_yoast_wpseo_title',
    ];

    foreach ($keys as $key) {
        register_post_meta('post', $key, [
            'show_in_rest' => true,
            'single'       => true,
            'type'         => 'string',
            'auth_callback' => function () {
                return current_user_can('edit_posts');
            },
        ]);
    }
});